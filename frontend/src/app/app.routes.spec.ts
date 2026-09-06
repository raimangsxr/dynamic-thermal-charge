import { describe, expect, it } from 'vitest';

import { routes } from './app.routes';

describe('application routes', () => {
  it('keeps one public configuration page and redirects the legacy alias', () => {
    const configuration = routes.find((route) => route.path === 'configuracion');
    const legacy = routes.find((route) => route.path === 'configuracion-sistema');

    expect(configuration?.loadComponent).toBeDefined();
    expect(legacy).toMatchObject({ redirectTo: 'configuracion', pathMatch: 'full' });
    expect(legacy?.loadComponent).toBeUndefined();
  });
});
