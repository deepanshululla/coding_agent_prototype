import clsx from 'clsx';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import Heading from '@theme/Heading';

import styles from './index.module.css';

function HomepageHeader() {
  const {siteConfig} = useDocusaurusContext();
  return (
    <header className={clsx('hero hero--agent', styles.heroBanner)}>
      <div className="container">
        <Heading as="h1" className="hero__title">
          {siteConfig.title}
        </Heading>
        <p className="hero__subtitle">{siteConfig.tagline}</p>
        <div className={styles.buttons}>
          <Link
            className="button button--primary button--lg"
            to="/docs/intro">
            Read the docs →
          </Link>
          <Link
            className="button button--secondary button--lg"
            to="/docs/getting-started/quickstart">
            Quickstart (5 min)
          </Link>
        </div>
        <pre className="terminal-snippet">
          <span className="comment"># one model string away from any provider</span>
          {'\n'}
          <span className="prompt">$</span> uv run main.py "add type hints to tools.py"
          {'\n'}
          <span className="comment">▸ read_file  ▸ edit_file  ▸ bash (pytest)  ✓ done</span>
        </pre>
      </div>
    </header>
  );
}

const FEATURES = [
  {
    title: 'The agent is a loop',
    body: 'No framework magic. An inner tool-call cycle wrapped in an outer follow-up loop — under 750 lines, the same shape pi.dev ships.',
    to: '/docs/architecture/the-agent-loop',
  },
  {
    title: 'Seven tools, parallel by default',
    body: 'read, write, edit, bash, grep, find, ls. Tool errors are returned as strings, never raised, so the model can reason and recover.',
    to: '/docs/tools/overview',
  },
  {
    title: 'Any provider, one string',
    body: 'LiteLLM normalizes 40+ providers to the OpenAI streaming format. Swap Claude for Gemini or GPT by changing one constant.',
    to: '/docs/architecture/provider-layer',
  },
];

function Feature({title, body, to}) {
  return (
    <div className={clsx('col col--4')}>
      <div className={styles.feature}>
        <Heading as="h3">{title}</Heading>
        <p>{body}</p>
        <Link to={to}>Learn more →</Link>
      </div>
    </div>
  );
}

export default function Home() {
  const {siteConfig} = useDocusaurusContext();
  return (
    <Layout
      title={`${siteConfig.title}`}
      description="Build a real terminal coding agent from scratch in Python.">
      <HomepageHeader />
      <main>
        <section className={styles.features}>
          <div className="container">
            <div className="row">
              {FEATURES.map((props, idx) => (
                <Feature key={idx} {...props} />
              ))}
            </div>
          </div>
        </section>
      </main>
    </Layout>
  );
}
