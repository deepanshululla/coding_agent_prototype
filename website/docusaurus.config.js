// @ts-check
// Docusaurus configuration for the "Coding Agent From Scratch" documentation site.
// Docs: https://docusaurus.io/docs/api/docusaurus-config

import {themes as prismThemes} from 'prism-react-renderer';

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'Coding Agent From Scratch',
  tagline: 'Build a real terminal coding agent in ~750 lines of Python',
  favicon: 'img/favicon.ico',

  url: 'https://your-org.github.io',
  baseUrl: '/coding-agent-from-scratch/',

  organizationName: 'your-org',
  projectName: 'coding-agent-from-scratch',

  onBrokenLinks: 'warn',

  markdown: {
    hooks: {
      // Moved here from the top level per the Docusaurus v4 migration notice.
      onBrokenMarkdownLinks: 'warn',
    },
  },

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      'classic',
      /** @type {import('@docusaurus/preset-classic').Options} */
      ({
        docs: {
          sidebarPath: './sidebars.js',
          routeBasePath: 'docs',
          // Point this at your repo to enable "Edit this page" links.
          editUrl:
            'https://github.com/your-org/coding-agent-from-scratch/tree/main/website/',
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      }),
    ],
  ],

  themeConfig:
    /** @type {import('@docusaurus/preset-classic').ThemeConfig} */
    ({
      image: 'img/social-card.png',
      colorMode: {
        defaultMode: 'dark',
        respectPrefersColorScheme: true,
      },
      navbar: {
        title: 'Coding Agent',
        logo: {
          alt: 'Coding Agent From Scratch',
          src: 'img/logo.svg',
        },
        items: [
          {
            type: 'docSidebar',
            sidebarId: 'docsSidebar',
            position: 'left',
            label: 'Docs',
          },
          {
            href: 'https://github.com/earendil-works/pi',
            label: 'pi.dev source',
            position: 'right',
          },
          {
            href: 'https://github.com/your-org/coding-agent-from-scratch',
            label: 'GitHub',
            position: 'right',
          },
        ],
      },
      footer: {
        style: 'dark',
        links: [
          {
            title: 'Docs',
            items: [
              {label: 'Introduction', to: '/docs/intro'},
              {label: 'Getting Started', to: '/docs/getting-started/quickstart'},
              {label: 'Architecture', to: '/docs/architecture/overview'},
              {label: 'API Reference', to: '/docs/reference/agent'},
            ],
          },
          {
            title: 'Concepts',
            items: [
              {label: 'The Agent Loop', to: '/docs/architecture/the-agent-loop'},
              {label: 'Tools', to: '/docs/tools/overview'},
              {label: 'Streaming', to: '/docs/architecture/streaming-and-events'},
            ],
          },
          {
            title: 'Sources',
            items: [
              {label: 'pi.dev', href: 'https://pi.dev/docs/latest'},
              {label: 'LiteLLM', href: 'https://docs.litellm.ai/'},
              {label: 'Anthropic API', href: 'https://docs.anthropic.com/'},
            ],
          },
        ],
        copyright: `Built as a learning project. Grounded in pi.dev and the Super 30 lecture.`,
      },
      prism: {
        theme: prismThemes.github,
        darkTheme: prismThemes.dracula,
        additionalLanguages: ['python', 'bash', 'json', 'diff'],
      },
    }),
};

export default config;
