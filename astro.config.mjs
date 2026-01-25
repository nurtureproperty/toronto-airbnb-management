// @ts-check
import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

// https://astro.build/config
export default defineConfig({
  site: 'https://www.nurturestays.ca',
  integrations: [
    sitemap({
      filter: (page) =>
        !page.includes('/index-old/') &&
        !page.includes('/thank-you/'),
    }),
  ],
});
