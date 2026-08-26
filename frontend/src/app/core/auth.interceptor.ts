/**
 * Adds the credential to every API call, and handles its rejection.
 *
 * The only place that reads the credential, and the only place that deals with a
 * 401. Doing either at each call site would guarantee forgetting one.
 *
 * The credential travels in the header, NEVER in the URL. In a URL it would end
 * up in the browser history and in nginx's access log.
 */

import {
  HttpErrorResponse,
  type HttpHandlerFn,
  type HttpInterceptorFn,
  type HttpRequest,
} from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, throwError } from 'rxjs';

import { Auth } from './auth';

export const authInterceptor: HttpInterceptorFn = (
  request: HttpRequest<unknown>,
  next: HttpHandlerFn,
) => {
  const auth = inject(Auth);
  const token = auth.token();

  const authorized =
    token === null
      ? request
      : request.clone({ setHeaders: { Authorization: `Bearer ${token}` } });

  return next(authorized).pipe(
    catchError((error: unknown) => {
      if (error instanceof HttpErrorResponse && error.status === 401) {
        // The credential is gone or was rotated on the server. Clearing the
        // session sends the operator back to the sign-in screen with an
        // explanation, instead of leaving every view showing a technical error.
        auth.signOut();
      }
      return throwError(() => error);
    }),
  );
};
