import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';

import { ParamHelp } from './param-help';

describe('ParamHelp', () => {
  it('shows detailed help on hover', async () => {
    await TestBed.configureTestingModule({ imports: [ParamHelp] }).compileComponents();
    const fixture = TestBed.createComponent(ParamHelp);
    fixture.componentRef.setInput('field', 'max_total_power_kw');
    fixture.detectChanges();

    const host = fixture.nativeElement as HTMLElement;
    expect(host.querySelector('.param-help-popup')).toBeNull();

    host.querySelector('.param-help')?.dispatchEvent(new Event('mouseenter'));
    fixture.detectChanges();

    const popup = host.querySelector('.param-help-popup');
    expect(popup).not.toBeNull();
    expect(popup?.textContent).toContain('Potencia máxima');
  });
});
