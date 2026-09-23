import {
  UNSET_CONTACT,
  UNSET_OPERATOR,
  UNSET_REGION,
  applyDeploymentFacts,
  contactEmailLink,
  hostingRegionText,
  operatorText,
} from '../utils/deploymentText';

const EMAIL = 'privacy@example.org';
const ORG = 'Example Org';
const ADDRESS = '1 Main St, Rome, Italy';
const SAMPLE =
  'Operated by {{OPERATOR}}. Hosted in {{HOSTING_REGION}}. ' +
  'Contact {{CONTACT_EMAIL_LINK}} or {{CONTACT_EMAIL_LINK}}.';

describe('deployment facts in the legal pages', () => {
  test('substitutes every token from the given facts', () => {
    const out = applyDeploymentFacts(SAMPLE, {
      operatorName: ORG,
      operatorAddress: ADDRESS,
      hostingRegion: 'the European Union',
      contactEmail: EMAIL,
    });
    expect(out).toBe(
      `Operated by ${ORG}, ${ADDRESS}. Hosted in the European Union. ` +
        `Contact [${EMAIL}](mailto:${EMAIL}) or [${EMAIL}](mailto:${EMAIL}).`
    );
  });

  test('renders neutral phrases, never placeholders, when nothing is set', () => {
    const out = applyDeploymentFacts(SAMPLE, {});
    expect(out).toBe(
      `Operated by ${UNSET_OPERATOR}. Hosted in ${UNSET_REGION}. ` +
        `Contact ${UNSET_CONTACT} or ${UNSET_CONTACT}.`
    );
    expect(out).not.toMatch(/\{\{|\}\}|\[.*\]\(mailto:/);
  });

  test('operator without an address is just the name', () => {
    expect(operatorText({ operatorName: `  ${ORG}  ` })).toBe(ORG);
  });

  test('an address without a name is ignored rather than shown alone', () => {
    expect(operatorText({ operatorAddress: 'Somewhere' })).toBe(UNSET_OPERATOR);
  });

  test('blank values count as unset', () => {
    expect(hostingRegionText({ hostingRegion: '   ' })).toBe(UNSET_REGION);
    expect(contactEmailLink({ contactEmail: '' })).toBe(UNSET_CONTACT);
  });

  test('reads the build-time configuration by default', () => {
    // No REACT_APP_* deployment variables are set in the test environment.
    expect(applyDeploymentFacts('{{OPERATOR}}')).toBe(UNSET_OPERATOR);
  });

  test('leaves markdown without tokens untouched', () => {
    const md = '# Title\n\nPlain text with [a link](https://example.org).';
    expect(applyDeploymentFacts(md, { contactEmail: 'x@y.z' })).toBe(md);
  });
});
