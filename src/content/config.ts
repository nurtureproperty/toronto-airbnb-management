import { defineCollection, z } from 'astro:content';

const blogCollection = defineCollection({
  type: 'content',
  schema: z.object({
    title: z.string(),
    description: z.string(),
    pubDate: z.string(),
    author: z.string().default('Nurture Airbnb Property Management'),
    category: z.string().default('News'),
    tags: z.array(z.string()).default([]),
    sourceUrl: z.string().optional(),
    sourceTitle: z.string().optional(),
    draft: z.boolean().default(false),
  }),
});

export const collections = {
  'blog': blogCollection,
};
