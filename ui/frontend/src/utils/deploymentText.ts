/**
 * Deployment-specific facts in the legal pages.
 *
 * The Privacy Policy and Terms of Service are shared markdown, but who
 * operates an instance, where it is hosted, its public address and how to
 * contact the operator differ per deployment. Those facts come from
 * build-time environment variables (`REACT_APP_OPERATOR_NAME`,
 * `REACT_APP_OPERATOR_ADDRESS`, `REACT_APP_HOSTING_REGION`,
 * `REACT_APP_SITE_URL`, `REACT_APP_CONTACT_EMAIL`; see
 * docs/admin/customization.md) and are substituted for the `{{...}}` tokens
 * in the markdown at render time.
 *
 * Unset values fall back to the reference deployment at evidencelab.ai, run
 * by Astrobagel in the United States, so a stock build states the facts of
 * the instance the docs were written for. Any other deployment sets its own.
 */
import { DEPLOYMENT } from '../config';

export interface DeploymentFacts {
  operatorName?: string;
  operatorAddress?: string;
  hostingRegion?: string;
  siteUrl?: string;
  contactEmail?: string;
}

/** The reference deployment, used for any value a build does not set. */
export const DEFAULT_OPERATOR_NAME = 'Astrobagel';
export const DEFAULT_HOSTING_REGION = 'the United States';
export const DEFAULT_SITE_URL = 'https://evidencelab.ai';
export const DEFAULT_CONTACT_EMAIL = 'evidencelab@astrobagel.com';

const clean = (value?: string): string => (value || '').trim();

/** Operator name plus address, e.g. "Example Org, 1 Main St, Country". */
export const operatorText = (facts: DeploymentFacts): string => {
  const name = clean(facts.operatorName) || DEFAULT_OPERATOR_NAME;
  const address = clean(facts.operatorAddress);
  return address ? `${name}, ${address}` : name;
};

/** The contact address itself, for places that render their own link. */
export const contactEmail = (facts: DeploymentFacts = DEPLOYMENT): string =>
  clean(facts.contactEmail) || DEFAULT_CONTACT_EMAIL;

/** A markdown mailto link for the contact address. */
export const contactEmailLink = (facts: DeploymentFacts): string => {
  const email = contactEmail(facts);
  return `[${email}](mailto:${email})`;
};

export const hostingRegionText = (facts: DeploymentFacts): string =>
  clean(facts.hostingRegion) || DEFAULT_HOSTING_REGION;

export const siteUrl = (facts: DeploymentFacts = DEPLOYMENT): string =>
  clean(facts.siteUrl) || DEFAULT_SITE_URL;

/** The site's host name, e.g. "evidencelab.ai", for prose. */
export const siteHost = (facts: DeploymentFacts): string =>
  siteUrl(facts).replace(/^https?:\/\//, '').replace(/\/+$/, '');

/**
 * Replace the deployment tokens in a markdown document.
 * Tokens: {{OPERATOR}}, {{HOSTING_REGION}}, {{SITE_URL}}, {{SITE_HOST}},
 * {{CONTACT_EMAIL_LINK}}.
 */
export const applyDeploymentFacts = (
  markdown: string,
  facts: DeploymentFacts = DEPLOYMENT
): string =>
  markdown
    .replace(/\{\{OPERATOR\}\}/g, operatorText(facts))
    .replace(/\{\{HOSTING_REGION\}\}/g, hostingRegionText(facts))
    .replace(/\{\{SITE_URL\}\}/g, siteUrl(facts))
    .replace(/\{\{SITE_HOST\}\}/g, siteHost(facts))
    .replace(/\{\{CONTACT_EMAIL_LINK\}\}/g, contactEmailLink(facts));
