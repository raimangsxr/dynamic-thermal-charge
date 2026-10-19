import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';

import type { AlertDto, AlertPageDto } from '../core/api.types';
import { Alerts } from './alerts';

function alertDto(id: number, overrides: Partial<AlertDto> = {}): AlertDto {
  return {
    id,
    alert_type: 'controller_unresponsive',
    severity: 'warning',
    title: `Aviso ${id}`,
    body: 'El controlador necesita atención.',
    episode_id: `episode-${id}`,
    session_id: null,
    opened_at: '2026-01-16T01:00:00Z',
    resolved_at: null,
    acknowledged_at: null,
    active: true,
    ...overrides,
  };
}

function alertPage(overrides: Partial<AlertPageDto> = {}): AlertPageDto {
  return {
    items: [alertDto(1)],
    view: 'active',
    limit_applied: 50,
    has_more: false,
    next_cursor: null,
    active_count: 1,
    maximum_severity: 'warning',
    ...overrides,
  };
}

describe('Alerts', () => {
  let fixture: ComponentFixture<Alerts>;
  let backend: HttpTestingController;

  beforeEach(async () => {
    TestBed.resetTestingModule();
    await TestBed.configureTestingModule({
      imports: [Alerts],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    fixture = TestBed.createComponent(Alerts);
    backend = TestBed.inject(HttpTestingController);
  });

  function load(page: AlertPageDto = alertPage()): HTMLElement {
    fixture.detectChanges();
    backend.expectOne((request) => request.url === '/api/v1/alerts' && request.params.get('view') === 'active').flush(page);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  it('uses Material tabs, cards and buttons for the alert inbox', () => {
    const element = load();

    expect(element.querySelector('mat-tab-group[data-testid="alerts-tabs"]')).not.toBeNull();
    expect(element.querySelector('mat-card.alert-card')).not.toBeNull();
    expect(element.querySelector('button[mat-stroked-button]')).not.toBeNull();
  });

  it('keeps active content inside the labelled Material tabpanel', () => {
    const element = load(alertPage({ has_more: true, next_cursor: 'opaque-cursor' }));
    const tabs = Array.from(element.querySelectorAll<HTMLElement>('[role="tab"]'));
    const panels = Array.from(element.querySelectorAll<HTMLElement>('[role="tabpanel"]'));
    const activePanel = panels.find((panel) => panel.getAttribute('aria-hidden') === 'false');

    expect(tabs).toHaveLength(2);
    expect(tabs[0]?.getAttribute('tabindex')).toBe('0');
    expect(tabs[1]?.getAttribute('tabindex')).toBe('-1');
    expect(activePanel).toBeDefined();
    expect(activePanel?.getAttribute('aria-labelledby')).toBe(tabs[0]?.id);
    expect(tabs[0]?.getAttribute('aria-controls')).toBe(activePanel?.id);
    expect(activePanel?.querySelector('[data-testid="alerts-panel-active"]')).not.toBeNull();
    expect(activePanel?.querySelector('.alert-tab-panel')?.classList.contains('alert-tab-panel')).toBe(true);
    expect(activePanel?.querySelector('.alert-list')).not.toBeNull();
    expect(activePanel?.querySelector('.load-more')).not.toBeNull();
    expect(element.querySelector('main > .alert-list')).toBeNull();
    expect(element.querySelector('main > .load-more')).toBeNull();
  });

  it('moves history content into its labelled panel without changing the flow', async () => {
    const element = load();

    const tabsBeforeChange = Array.from(element.querySelectorAll<HTMLElement>('[role="tab"]'));
    tabsBeforeChange[1]?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    fixture.detectChanges();
    await Promise.resolve();
    const request = backend.expectOne((candidate) => candidate.url === '/api/v1/alerts' && candidate.params.get('view') === 'history');
    request.flush(alertPage({ view: 'history' }));
    fixture.detectChanges();

    const tabs = Array.from(element.querySelectorAll<HTMLElement>('[role="tab"]'));
    const activePanel = Array.from(element.querySelectorAll<HTMLElement>('[role="tabpanel"]'))
      .find((panel) => panel.getAttribute('aria-hidden') === 'false');
    expect(tabs[0]?.getAttribute('tabindex')).toBe('-1');
    expect(tabs[1]?.getAttribute('tabindex')).toBe('0');
    expect(activePanel?.getAttribute('aria-labelledby')).toBe(tabs[1]?.id);
    expect(tabs[1]?.getAttribute('aria-controls')).toBe(activePanel?.id);
    expect(activePanel?.querySelector('[data-testid="alerts-panel-history"]')).not.toBeNull();
    expect(activePanel?.querySelector('.alert-list')).not.toBeNull();
  });

  it('keeps the active/history requests when changing Material tabs', () => {
    load();

    fixture.componentInstance.selectTab(1);
    const request = backend.expectOne((candidate) => candidate.url === '/api/v1/alerts' && candidate.params.get('view') === 'history');
    expect(request.request.params.get('limit')).toBe('50');
    request.flush(alertPage({ view: 'history', items: [], active_count: 0, maximum_severity: null }));
  });

  it('keeps acknowledgement on the existing endpoint and view', () => {
    load();

    fixture.componentInstance.acknowledge(1);
    const request = backend.expectOne((candidate) => candidate.url === '/api/v1/alerts/1/ack');
    expect(request.request.method).toBe('POST');
    expect(request.request.params.get('view')).toBe('active');
    expect(request.request.params.get('limit')).toBe('50');
    request.flush(alertPage({ items: [alertDto(1, { acknowledged_at: '2026-01-16T01:05:00Z' })] }));
  });

  it('appends the next cursor page without changing pagination semantics', () => {
    load(alertPage({ has_more: true, next_cursor: 'opaque-cursor' }));

    fixture.componentInstance.nextPage();
    const request = backend.expectOne((candidate) => candidate.url === '/api/v1/alerts' && candidate.params.get('cursor') === 'opaque-cursor');
    expect(request.request.params.get('view')).toBe('active');
    expect(request.request.params.get('limit')).toBe('50');
    request.flush(alertPage({ items: [alertDto(2)], has_more: false, next_cursor: null }));

    expect(fixture.componentInstance.page()?.items.map((item) => item.id)).toEqual([1, 2]);
  });

  afterEach(() => backend.verify());
});
