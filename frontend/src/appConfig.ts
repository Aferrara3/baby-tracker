import type { TrackerButtonConfig, TrackerSymbolOption } from './trackerButtons';

export interface AppCopy {
  auth_badge_label: string;
  auth_heading: string;
  auth_subheading: string;
  create_account_label: string;
  register_name_placeholder: string;
  settings_name_label: string;
  settings_name_placeholder: string;
  enable_sync_name_help: string;
  header_context_with_name: string;
  header_context_without_name: string;
}

export interface AppConfig {
  profile_id: string;
  app_name: string;
  copy: AppCopy;
  available_symbols: TrackerSymbolOption[];
  button_templates: TrackerButtonConfig[];
  tracker_buttons_per_page: number;
  max_tracker_button_pages: number;
  placeholder_button_label_prefix: string;
}

export const FALLBACK_APP_CONFIG: AppConfig = {
  profile_id: 'fallback',
  app_name: 'Tracker',
  copy: {
    auth_badge_label: 'Tracker sign-in',
    auth_heading: 'Tracker',
    auth_subheading: 'Create an account to keep trackers and calendars separated.',
    create_account_label: 'Create account',
    register_name_placeholder: 'Name (optional)',
    settings_name_label: 'Name',
    settings_name_placeholder: 'Name',
    enable_sync_name_help: 'Enable sync will save the current name and share-email edits automatically first.',
    header_context_with_name: "{tracked_name}'s tracker",
    header_context_without_name: "{username}'s tracker",
  },
  available_symbols: [{ key: 'help-circle', label: 'Other', emoji: '❓', keywords: ['other'] }],
  button_templates: [
    {
      id: 'other',
      label: 'Other',
      icon_key: 'help-circle',
      color_key: 'slate',
      position: 0,
      emoji: '❓',
      title: '❓ Other',
    },
  ],
  tracker_buttons_per_page: 8,
  max_tracker_button_pages: 3,
  placeholder_button_label_prefix: 'Other',
};
