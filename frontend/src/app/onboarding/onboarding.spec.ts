import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { describe, expect, it } from 'vitest';

import { Onboarding } from './onboarding';

describe('Onboarding', () => {
  it('clears both one-use credentials after completion', async () => {
    await TestBed.configureTestingModule({ imports: [Onboarding], providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([{ path: 'configuracion-sistema', component: Onboarding }])] }).compileComponents();
    const backend = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(Onboarding); fixture.detectChanges();
    backend.expectOne('/api/v1/onboarding/status').flush({ required: true, state: 'unconfigured' });
    const component = fixture.componentInstance;
    component.credential = 'one-use'; component.administratorToken = 'a'.repeat(40); component.confirmation = 'a'.repeat(40);
    component.complete();
    const request = backend.expectOne('/api/v1/onboarding/complete');
    expect(request.request.body.onboarding_credential).toBe('one-use');
    request.flush(null); fixture.detectChanges();
    expect(component.credential).toBe(''); expect(component.administratorToken).toBe(''); expect(component.confirmation).toBe('');
  });
});
