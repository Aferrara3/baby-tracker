import chatBetaWhitelist from '../../shared/chat-beta-whitelist.json';

function normalizeUsername(value: string): string {
  return value.trim().toLowerCase();
}

const CHAT_BETA_USERNAME_WHITELIST = new Set(
  (chatBetaWhitelist.usernames ?? [])
    .map((value) => (typeof value === 'string' ? normalizeUsername(value) : ''))
    .filter(Boolean),
);

export function isChatBetaEnabledForUsername(username: string | null | undefined): boolean {
  if (!username) {
    return false;
  }
  return CHAT_BETA_USERNAME_WHITELIST.has(normalizeUsername(username));
}
