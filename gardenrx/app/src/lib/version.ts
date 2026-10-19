import pkg from '../../package.json';

/** App version, sourced from package.json so the value can't drift. */
export const APP_VERSION: string = pkg.version;
