import {
  DEFAULT_CONTACT_EMAIL,
  DEFAULT_HOSTING_REGION,
  DEFAULT_OPERATOR_NAME,
  DEFAULT_SITE_URL,
  applyDeploymentFacts,
  contactEmailLink,
  hostingRegionText,
  operatorText,
  siteHost,
} from '../utils/deploymentText';

const EMAIL = 'privacy@example.org';
const ORG = 'Example Org';
const ADDRESS = '1 Main St, Rome, Italy';
const SAMPLE =
  'The {{SITE_HOST}} instance ({{SITE_URL}}) is operated by {{OPERATOR}}. ' +
  'Hosted in {{HOSTING_REGION}}. Contact {{CONTACT_EMAIL_LINK}} or {{CONTACT_EMAIL_LINK}}.';

describe('deployment facts in the legal pages', () => {
  test('substitutes every token from the given facts', () => {
    const out = applyDeploymentFacts(SAMPLE, {
      operatorName: ORG,
      operatorAddress: ADDRESS,
      hostingRegion: 'the European Union',
      siteUrl: 'https://evidence.example.org/',
      contactEmail: EMAIL,
    });
    expect(out).toBe(
      `The evidence.example.org instance (https://evidence.example.org/) is operated by ${ORG}, ${ADDRESS}. ` +
        `Hosted in the European Union. Contact [${EMAIL}](mailto:${EMAIL}) or [${EMAIL}](mailto:${EMAIL}).`
    );
  });

  test('falls back to the reference deployment when nothing is set', () => {
    const out = applyDeploymentFacts(SAMPLE, {});
    expect(out).toBe(
      `The evidencelab.ai instance (${DEFAULT_SITE_URL}) is operated by ${DEFAULT_OPERATOR_NAME}. ` +
        `Hosted in ${DEFAULT_HOSTING_REGION}. ` +
        `Contact [${DEFAULT_CONTACT_EMAIL}](mailto:${DEFAULT_CONTACT_EMAIL}) or ` +
        `[${DEFAULT_CONTACT_EMAIL}](mailto:${DEFAULT_CONTACT_EMAIL}).`
    );
    expect(out).not.toMatch(/\{\{|\}\}/);
  });

  test('the defaults are the evidencelab.ai values', () => {
    expect(DEFAULT_OPERATOR_NAME).toBe('Astrobagel');
    expect(DEFAULT_HOSTING_REGION).toBe('the United States');
    expect(DEFAULT_SITE_URL).toBe('https://evidencelab.ai');
    expect(DEFAULT_CONTACT_EMAIL).toBe('evidencelab@astrobagel.com');
  });

  test('operator without an address is just the name', () => {
    expect(operatorText({ operatorName: `  ${ORG}  ` })).toBe(ORG);
  });

  test('an address alone is appended to the default operator', () => {
    expect(operatorText({ operatorAddress: 'Somewhere' })).toBe(
      `${DEFAULT_OPERATOR_NAME}, Somewhere`
    );
  });

  test('blank values count as unset', () => {
    expect(hostingRegionText({ hostingRegion: '   ' })).toBe(DEFAULT_HOSTING_REGION);
    expect(contactEmailLink({ contactEmail: '' })).toBe(
      `[${DEFAULT_CONTACT_EMAIL}](mailto:${DEFAULT_CONTACT_EMAIL})`
    );
  });

  test('site host strips the scheme and trailing slash', () => {
    expect(siteHost({ siteUrl: 'http://lab.example.org/' })).toBe('lab.example.org');
    expect(siteHost({})).toBe('evidencelab.ai');
  });

  test('reads the build-time configuration by default', () => {
    // No REACT_APP_* deployment variables are set in the test environment.
    expect(applyDeploymentFacts('{{OPERATOR}}')).toBe(DEFAULT_OPERATOR_NAME);
  });

  test('leaves markdown without tokens untouched', () => {
    const md = '# Title\n\nPlain text with [a link](https://example.org).';
    expect(applyDeploymentFacts(md, { contactEmail: 'x@y.z' })).toBe(md);
  });
});
