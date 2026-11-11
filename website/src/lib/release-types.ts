export type Asset = { name: string; size: number; url: string };

/** A published installer. `installerUrl` is the .exe asset, or the configured DOWNLOAD_URL. */
export type Release = { version: string; published: string; url: string; installerUrl: string; assets: Asset[] };
