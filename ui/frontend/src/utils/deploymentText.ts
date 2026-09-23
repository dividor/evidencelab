/**
 * Deployment-specific facts in the legal pages.
 *
 * The Privacy Policy and Terms of Service are shared markdown, but who
 * operates an instance, where it is hosted and how to contact them differ
 * per deployment. Those facts are set with build-time environment variables
 * (`REACT_APP_OPERATOR_NAME`, `REACT_APP_OPERATOR_ADDRESS`,
 * `REACT_APP_HOSTING_REGION`, `REACT_APP_CONTACT_EMAIL`; see
 * docs/admin/customization.md) and substituted for the `{{...}}` tokens in
 * the markdown at render time, so no deployment's details live in the repo.
 *
 * When a value is not set, the token renders as a neutral phrase rather than
 * a placeholder or a made-up value.
 */
import { DEPLOYMENT } from '../config';

export interface DeploymentFacts {
  operatorName?: string;
  operatorAddress?: string;
  hostingRegion?: string;
  contactEmail?: string;
}

// Shown when a deployment has not set the variable: honest about the gap
// rather than inventing a value, and visible enough that an operator notices.
export const UNSET_OPERATOR =
  'an organisation that has not yet published its details on this page';
export const UNSET_REGION = 'a hosting region the operator has not yet published here';
export const UNSET_CONTACT = 'a contact address the operator has not yet published here';

const clean = (value?: string): string => (value || '').trim();

/** Operator name plus address, e.g. "Example Org, 1 Main St, Country". */
export const operatorText = (facts: DeploymentFacts): string => {
  const name = clean(facts.operatorName);
  const address = clean(facts.operatorAddress);
  if (!name) return UNSET_OPERATOR;
  return address ? `${name}, ${address}` : name;
};

/** A markdown mailto link for the contact address, or a neutral phrase. */
export const contactEmailLink = (facts: DeploymentFacts): string => {
  const email = clean(facts.contactEmail);
  return email ? `[${email}](mailto:${email})` : UNSET_CONTACT;
};

export const hostingRegionText = (facts: DeploymentFacts): string =>
  clean(facts.hostingRegion) || UNSET_REGION;

/**
 * Replace the deployment tokens in a markdown document.
 * Tokens: {{OPERATOR}}, {{HOSTING_REGION}}, {{CONTACT_EMAIL_LINK}}.
 */
export const applyDeploymentFacts = (
  markdown: string,
  facts: DeploymentFacts = DEPLOYMENT
): string =>
  markdown
    .replace(/\{\{OPERATOR\}\}/g, operatorText(facts))
    .replace(/\{\{HOSTING_REGION\}\}/g, hostingRegionText(facts))
    .replace(/\{\{CONTACT_EMAIL_LINK\}\}/g, contactEmailLink(facts));
