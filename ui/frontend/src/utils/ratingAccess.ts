import { ANONYMOUS_RATINGS, USER_MODULE } from '../config';

/**
 * Whether to show rating stars. Ratings live in the user module, so they need
 * it on; a visitor who is not signed in may rate only when the deployment
 * turns on `features.anonymous_ratings`, which the API checks as well.
 */
export const canRateWith = (
  isAuthenticated: boolean,
  userModule: boolean,
  anonymousRatings: boolean
): boolean => userModule && (isAuthenticated || anonymousRatings);

export const canRate = (isAuthenticated: boolean): boolean =>
  canRateWith(isAuthenticated, USER_MODULE, ANONYMOUS_RATINGS);
