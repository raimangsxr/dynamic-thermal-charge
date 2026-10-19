import { Component, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { firstValueFrom, forkJoin } from 'rxjs';

import { Api } from '../core/api';
import type { ConfigDto, PushRegistrationDto, RoomDto } from '../core/api.types';

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

type PushStatus =
  | 'checking'
  | 'enabled'
  | 'revoked'
  | 'browser-capability'
  | 'insecure-context'
  | 'permission-denied'
  | 'permission-required'
  | 'permission-error'
  | 'server-unconfigured'
  | 'server-invalid-key'
  | 'subscription-error'
  | 'registration-error'
  | 'revoke-error'
  | 'revoking';

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
  readonly pushStatus = signal<PushStatus | null>(null);

  constructor() {
    this.refresh();
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

  async registerPush(): Promise<void> {
    const capabilityIssue = this.pushCapabilityIssue();
    if (capabilityIssue) {
      this.pushStatus.set(capabilityIssue);
      return;
    }

    this.pushStatus.set('checking');
    const notification = globalThis.Notification;
    let permission: NotificationPermission;
    if (notification.permission === 'denied') {
      this.pushStatus.set('permission-denied');
      return;
    }
    try {
      permission = notification.permission === 'granted'
        ? 'granted'
        : await notification.requestPermission();
    } catch {
      this.pushStatus.set('permission-error');
      return;
    }
    if (permission !== 'granted') {
      this.pushStatus.set(permission === 'denied' ? 'permission-denied' : 'permission-required');
      return;
    }

    let publicKey: string | null;
    try {
      publicKey = (await firstValueFrom(this.api.pushPublicKey())).public_key;
    } catch {
      this.pushStatus.set('server-unconfigured');
      return;
    }
    if (!publicKey) {
      this.pushStatus.set('server-unconfigured');
      return;
    }

    let applicationServerKey: ArrayBuffer;
    try {
      applicationServerKey = this.decodeKey(publicKey);
    } catch {
      this.pushStatus.set('server-invalid-key');
      return;
    }

    let subscription: PushSubscription;
    try {
      const registration = await navigator.serviceWorker.register('/sw.js');
      const pushManager = registration.pushManager;
      if (!pushManager) {
        this.pushStatus.set('browser-capability');
        return;
      }
      const existingSubscription = typeof pushManager.getSubscription === 'function'
        ? await pushManager.getSubscription()
        : null;
      subscription = existingSubscription
        ?? await pushManager.subscribe({ userVisibleOnly: true, applicationServerKey });
    } catch {
      this.pushStatus.set('subscription-error');
      return;
    }

    const json = subscription.toJSON();
    const endpoint = json.endpoint;
    const keys = json.keys;
    if (!endpoint || !keys?.['p256dh'] || !keys['auth']) {
      this.pushStatus.set('subscription-error');
      return;
    }

    try {
      const result = await firstValueFrom(this.api.registerPush({
        browser_id: this.browserId(),
        endpoint,
        keys: { p256dh: keys['p256dh'], auth: keys['auth'] },
      }));
      this.pushStatus.set(this.mapPushRegistrationStatus(result.status));
    } catch {
      this.pushStatus.set('registration-error');
    }
  }

  revokePush(): void {
    this.pushStatus.set('revoking');
    this.api.revokePush(this.browserId()).subscribe({
      next: (result) => this.pushStatus.set(this.mapPushRegistrationStatus(result.status)),
      error: () => this.pushStatus.set('revoke-error'),
    });
  }

  pushStatusText(status: PushStatus): string {
    switch (status) {
      case 'checking': return 'Comprobando el navegador y preparando los avisos…';
      case 'enabled': return 'Avisos del navegador activados.';
      case 'revoked': return 'Avisos del navegador revocados.';
      case 'browser-capability': return 'Este navegador no ofrece avisos web compatibles. Usa un navegador con Web Push y vuelve a intentarlo.';
      case 'insecure-context': return 'Los avisos del navegador requieren HTTPS o localhost. Abre el panel en un contexto seguro y vuelve a intentarlo.';
      case 'permission-denied': return 'Los avisos están bloqueados para este sitio. Permítelos en la configuración del navegador y vuelve a intentarlo.';
      case 'permission-required': return 'No se concedió permiso para avisos. Permítelos para este sitio y vuelve a intentarlo.';
      case 'permission-error': return 'No se pudo solicitar permiso para avisos. Comprueba la configuración del navegador y vuelve a intentarlo.';
      case 'server-unconfigured': return 'El servidor no tiene configurada la clave pública de avisos. Configúrala y vuelve a intentarlo.';
      case 'server-invalid-key': return 'La configuración de avisos del servidor no es válida. Revisa la clave VAPID y vuelve a intentarlo.';
      case 'subscription-error': return 'No se pudo suscribir este navegador a los avisos. Comprueba el permiso y la conexión y vuelve a intentarlo.';
      case 'registration-error': return 'No se pudo guardar la suscripción de avisos. Comprueba la conexión y vuelve a intentarlo.';
      case 'revoking': return 'Revocando los avisos del navegador…';
      case 'revoke-error': return 'No se pudieron revocar los avisos. Comprueba la conexión y vuelve a intentarlo.';
    }
  }

  private pushCapabilityIssue(): PushStatus | null {
    if (globalThis.isSecureContext === false) return 'insecure-context';
    if (
      typeof navigator === 'undefined'
      || !('serviceWorker' in navigator)
      || typeof navigator.serviceWorker?.register !== 'function'
      || !('PushManager' in globalThis)
      || typeof globalThis.Notification !== 'function'
      || typeof globalThis.Notification.requestPermission !== 'function'
    ) {
      return 'browser-capability';
    }
    return null;
  }

  private mapPushRegistrationStatus(status: PushRegistrationDto['status']): PushStatus {
    switch (status.trim().toLowerCase()) {
      case 'active': return 'enabled';
      case 'revoked': return 'revoked';
      // The backend uses this status when its VAPID configuration is absent.
      // Keep the technical value out of the UI and preserve an actionable state.
      case 'unsupported': return 'server-unconfigured';
      default: return 'registration-error';
    }
  }

  progress(session: RoomDto['session']): number {
    const value = session?.metrics['progress'];
    return typeof value === 'number' ? value * 100 : 0;
  }

  statusLabel(status: RoomDto['status']): string {
    return ({
      approximate: 'Aproximada',
      estimated: 'Estimada',
      calibrating: 'En calibración',
      calibrated: 'Calibrada',
      failed: 'Fallida',
      cancelled: 'Cancelada',
      manually_adjusted: 'Ajustada manualmente',
    } as Record<string, string>)[status] ?? status;
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
    if (!/^[A-Za-z0-9_-]+={0,2}$/.test(value)) throw new Error('invalid VAPID public key encoding');
    const encoded = value.replace(/=+$/, '');
    if (!encoded || encoded.length % 4 === 1) throw new Error('invalid VAPID public key encoding');
    const padding = '='.repeat((4 - encoded.length % 4) % 4);
    let raw: string;
    try {
      raw = atob(encoded.replace(/-/g, '+').replace(/_/g, '/') + padding);
    } catch {
      throw new Error('invalid VAPID public key encoding');
    }
    const bytes = Uint8Array.from(raw, (character) => character.charCodeAt(0));
    if (bytes.length !== 65 || bytes[0] !== 0x04) throw new Error('invalid VAPID public key shape');
    return bytes.buffer as ArrayBuffer;
  }
}
