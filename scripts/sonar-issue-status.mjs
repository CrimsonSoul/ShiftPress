const CANONICAL_STATUSES = new Set(['OPEN', 'CONFIRMED', 'ACCEPTED', 'FALSE_POSITIVE', 'FIXED']);
const LEGACY_STATUS_WITHOUT_RESOLUTION = Object.freeze({
  ACCEPTED: 'ACCEPTED',
  CONFIRMED: 'CONFIRMED',
  FALSE_POSITIVE: 'FALSE_POSITIVE',
  FIXED: 'FIXED',
  OPEN: 'OPEN',
  REOPENED: 'OPEN',
});
const LEGACY_STATUS_WITH_RESOLUTION = Object.freeze({
  'ACCEPTED:WONTFIX': 'ACCEPTED',
  'FALSE_POSITIVE:FALSE-POSITIVE': 'FALSE_POSITIVE',
  'FALSE_POSITIVE:FALSE_POSITIVE': 'FALSE_POSITIVE',
  'FIXED:FIXED': 'FIXED',
  'RESOLVED:FALSE-POSITIVE': 'FALSE_POSITIVE',
  'RESOLVED:FALSE_POSITIVE': 'FALSE_POSITIVE',
  'RESOLVED:FIXED': 'FIXED',
  'RESOLVED:WONTFIX': 'ACCEPTED',
});

function optionalUppercase(value) {
  if (value === undefined || value === null) return null;
  if (typeof value !== 'string' || value.trim().length === 0) {
    throw new Error('Sonar returned unsupported issue status metadata.');
  }
  return value.toUpperCase();
}

function normalizeLegacyStatus(status, resolution) {
  const normalized =
    resolution === null
      ? LEGACY_STATUS_WITHOUT_RESOLUTION[status]
      : LEGACY_STATUS_WITH_RESOLUTION[`${status}:${resolution}`];
  if (normalized) return normalized;
  throw new Error('Sonar returned unsupported issue status metadata.');
}

export function normalizeSonarIssueStatus(issue) {
  const legacyStatus = optionalUppercase(issue?.status);
  if (legacyStatus === null) {
    throw new Error('Sonar returned unsupported issue status metadata.');
  }
  const resolution = optionalUppercase(issue.resolution);
  const legacyCanonical = normalizeLegacyStatus(legacyStatus, resolution);
  const canonical = optionalUppercase(issue.issueStatus);
  if (canonical === null) return legacyCanonical;
  if (!CANONICAL_STATUSES.has(canonical)) {
    throw new Error('Sonar returned unsupported issue status metadata.');
  }
  if (canonical !== legacyCanonical) {
    throw new Error('Sonar returned conflicting canonical and legacy issue status metadata.');
  }
  return canonical;
}
