import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { beforeEach, describe, expect, it } from 'vitest';

import { Auth } from '../auth';
import { Login } from './login';

describe('Login', () => {
  beforeEach(() => {
    sessionStorage.clear();
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      imports: [Login],
      providers: [provideRouter([])],
    });
  });

  it('shows a rejected credential message below the credential field', () => {
    TestBed.inject(Auth).rejectCredential();
    const fixture = TestBed.createComponent(Login);
    fixture.detectChanges();

    const element = fixture.nativeElement as HTMLElement;
    const input = element.querySelector('#token');
    const error = element.querySelector('[data-testid="login-error"]');
    expect(input).not.toBeNull();
    expect(error).not.toBeNull();
    expect(error?.textContent).toContain('La credencial no es válida o ha caducado.');
    expect(input!.compareDocumentPosition(error!) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0);
  });
});
