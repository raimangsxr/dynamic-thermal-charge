import { Component, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';

import { Api } from '../core/api';
import type { ConfigDto, OperatorNotificationDto, RoomDto } from '../core/api.types';

interface RoomCard {
  heater: ConfigDto['heaters'][number];
  room: RoomDto;
  estimate: {
    surface_m2: number;
    walls_exterior: number;
    windows_m2: number;
    insulation: 'poor' | 'medium' | 'good';
    height_m: number;
    other_heat_sources_kw: number;
  };
}

@Component({
  selector: 'dtc-calibration',
  imports: [CommonModule, FormsModule],
  templateUrl: './calibration.html',
  styleUrl: './calibration.css',
})
export class Calibration {
  private readonly api = inject(Api);
  readonly cards = signal<RoomCard[]>([]);
  readonly revision = signal(0);
  readonly loading = signal(true);
  readonly message = signal<string | null>(null);
  readonly pushStatus = signal<string | null>(null);
  readonly notifications = signal<OperatorNotificationDto[]>([]);

  constructor() {
    this.refresh();
    this.api.notifications().subscribe({ next: (page) => this.notifications.set(page.items), error: () => undefined });
  }

  acknowledge(notification: OperatorNotificationDto): void {
    this.api.acknowledgeNotification(notification.id).subscribe({
      next: (page) => this.notifications.set(page.items),
      error: () => this.message.set('No se pudo acusar el aviso.'),
    });
  }

  refresh(): void {
    this.loading.set(true);
    this.api.config().subscribe({
      next: (config) => {
        this.revision.set(config.config_revision);
        forkJoin(config.heaters.map((heater) => this.api.room(heater.id))).subscribe({
          next: (rooms) => {
            this.cards.set(rooms.map((room, index) => ({
              heater: config.heaters[index],
              room,
              estimate: {
                surface_m2: 20,
                walls_exterior: 1,
                windows_m2: 2,
                insulation: 'medium',
                height_m: 2.5,
                other_heat_sources_kw: 0,
              },
            })));
            this.loading.set(false);
          },
          error: () => { this.message.set('No se pudo leer el estado de las estancias.'); this.loading.set(false); },
        });
      },
      error: () => { this.message.set('No se pudo leer la configuración.'); this.loading.set(false); },
    });
  }

  start(card: RoomCard): void {
    this.message.set(null);
    this.api.startCalibration(card.heater.id).subscribe({
      next: (result) => { this.revision.set(result.revision); this.replace(card.heater.id, result.room); this.message.set('Calibración iniciada.'); },
      error: () => this.message.set('No se pudo iniciar la calibración; revisa las entradas recientes y el modo AUTO.'),
    });
  }

  cancel(card: RoomCard): void {
    this.api.cancelCalibration(card.heater.id).subscribe({
      next: (result) => { this.revision.set(result.revision); this.replace(card.heater.id, result.room); this.message.set('Calibración cancelada.'); },
      error: () => this.message.set('No se pudo cancelar la calibración.'),
    });
  }

  estimate(card: RoomCard): void {
    this.api.estimateRoom(card.heater.id, { expected_revision: this.revision(), ...card.estimate }).subscribe({
      next: (result) => { this.revision.set(result.revision); this.replace(card.heater.id, result.room); this.message.set('Estimación aplicada.'); },
      error: () => this.message.set('La estimación no cumple los límites definidos.'),
    });
  }

  saveAdvanced(card: RoomCard): void {
    this.api.patchRoom(card.heater.id, {
      expected_revision: this.revision(),
      capacity_kwh_per_c: card.room.capacity_kwh_per_c,
      loss_kw_per_c: card.room.loss_kw_per_c,
    }).subscribe({
      next: (room) => { this.replace(card.heater.id, room); this.revision.update((value) => value + 1); this.message.set('Parámetros guardados.'); },
      error: () => this.message.set('Los parámetros han cambiado; vuelve a cargar antes de guardar.'),
    });
  }

  registerPush(): void {
    if (!('serviceWorker' in navigator) || !('PushManager' in globalThis) || !('Notification' in globalThis)) {
      this.pushStatus.set('unsupported');
      return;
    }
    Notification.requestPermission().then((permission) => {
      if (permission !== 'granted') { this.pushStatus.set('denied'); return; }
      this.api.pushPublicKey().subscribe({
        next: (key) => {
          if (!key.public_key) { this.pushStatus.set('unsupported'); return; }
          navigator.serviceWorker.register('/sw.js').then((registration) =>
            registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: this.decodeKey(key.public_key!) }),
          ).then((subscription) => {
            const json = subscription.toJSON();
            const endpoint = json.endpoint;
            const keys = json.keys;
            if (!endpoint || !keys?.['p256dh'] || !keys['auth']) throw new Error('push subscription incomplete');
            return this.api.registerPush({ browser_id: this.browserId(), endpoint, keys: { p256dh: keys['p256dh'], auth: keys['auth'] } }).toPromise();
          }).then((result) => this.pushStatus.set(result?.status ?? 'error')).catch(() => this.pushStatus.set('error'));
        },
        error: () => this.pushStatus.set('error'),
      });
    });
  }

  revokePush(): void {
    this.api.revokePush(this.browserId()).subscribe({ next: (result) => this.pushStatus.set(result.status), error: () => this.pushStatus.set('error') });
  }

  progress(session: RoomDto['session']): number {
    const value = session?.metrics['progress'];
    return typeof value === 'number' ? value * 100 : 0;
  }

  private replace(id: string, room: RoomDto): void {
    this.cards.update((cards) => cards.map((card) => card.heater.id === id ? { ...card, room } : card));
  }

  private browserId(): string {
    const key = 'dtc-push-browser-id';
    // The panel deliberately never persists credentials or identifiers beyond
    // the tab lifetime; the backend still deduplicates attempts by the active
    // subscription's browser id.
    const existing = sessionStorage.getItem(key);
    if (existing) return existing;
    const value = crypto.randomUUID();
    sessionStorage.setItem(key, value);
    return value;
  }

  private decodeKey(value: string): ArrayBuffer {
    const padding = '='.repeat((4 - value.length % 4) % 4);
    const raw = atob(value.replace(/-/g, '+').replace(/_/g, '/') + padding);
    const bytes = Uint8Array.from(raw, (character) => character.charCodeAt(0));
    return bytes.buffer as ArrayBuffer;
  }
}
