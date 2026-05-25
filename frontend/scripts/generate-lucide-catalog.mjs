import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const frontendDir = path.resolve(__dirname, '..');
const repoRoot = path.resolve(frontendDir, '..');
const tagsPath = path.join(frontendDir, 'node_modules', 'lucide-static', 'tags.json');
const iconNodesPath = path.join(frontendDir, 'node_modules', 'lucide-static', 'icon-nodes.json');
const outputPath = path.join(repoRoot, 'shared', 'lucide-catalog.json');

const categoryMatchers = [
  { category: 'food', keywords: ['pizza', 'pasta', 'salad', 'sandwich', 'soup', 'cookie', 'cake', 'beef', 'drumstick', 'utensils', 'fork', 'meal', 'drink', 'wine', 'beer', 'martini', 'coffee', 'apple', 'carrot', 'ice cream'] },
  { category: 'health', keywords: ['pill', 'medicine', 'health', 'doctor', 'stethoscope', 'temperature', 'heart', 'pulse', 'vitals', 'hospital', 'scan'] },
  { category: 'body', keywords: ['toilet', 'bathroom', 'poop', 'pee', 'droplet', 'foot', 'biceps'] },
  { category: 'exercise', keywords: ['activity', 'exercise', 'fitness', 'dumbbell', 'workout', 'bike', 'swim', 'walk', 'footprints'] },
  { category: 'travel', keywords: ['car', 'bus', 'train', 'plane', 'trip', 'travel'] },
  { category: 'home', keywords: ['house', 'bath', 'shower', 'shopping', 'cart', 'bag', 'home', 'chores'] },
  { category: 'work', keywords: ['briefcase', 'laptop', 'calendar', 'appointment', 'phone', 'book', 'notebook'] },
  { category: 'mood', keywords: ['smile', 'frown', 'sparkles', 'love', 'care'] },
];

const emojiMatchers = [
  { emoji: '🍕', keywords: ['pizza'] },
  { emoji: '🍝', keywords: ['pasta', 'spaghetti', 'lasagna', 'noodle', 'utensils-crossed'] },
  { emoji: '🍽️', keywords: ['meal', 'food', 'utensils', 'restaurant', 'dinner'] },
  { emoji: '🥗', keywords: ['salad', 'greens'] },
  { emoji: '🥪', keywords: ['sandwich'] },
  { emoji: '🍲', keywords: ['soup', 'cooking', 'pot', 'broth'] },
  { emoji: '🍪', keywords: ['cookie'] },
  { emoji: '🎂', keywords: ['cake'] },
  { emoji: '☕', keywords: ['coffee'] },
  { emoji: '🥤', keywords: ['soda', 'cup-soda', 'soft drink'] },
  { emoji: '🍺', keywords: ['beer'] },
  { emoji: '🍸', keywords: ['martini', 'cocktail'] },
  { emoji: '🍷', keywords: ['wine'] },
  { emoji: '🍎', keywords: ['apple', 'fruit'] },
  { emoji: '🥕', keywords: ['carrot', 'veggie'] },
  { emoji: '🍖', keywords: ['drumstick', 'protein'] },
  { emoji: '🥩', keywords: ['beef'] },
  { emoji: '🍨', keywords: ['ice-cream', 'dessert'] },
  { emoji: '💩', keywords: ['toilet', 'poop', 'bowel', 'bathroom'] },
  { emoji: '💧', keywords: ['pee', 'urine', 'droplet', 'water'] },
  { emoji: '😴', keywords: ['sleep', 'bed', 'night', 'moon'] },
  { emoji: '🏋️', keywords: ['exercise', 'workout', 'fitness', 'gym', 'dumbbell', 'biceps'] },
  { emoji: '🚶', keywords: ['walk', 'footprints', 'steps'] },
  { emoji: '🚴', keywords: ['bike', 'ride'] },
  { emoji: '🏊', keywords: ['swim', 'waves-ladder'] },
  { emoji: '📝', keywords: ['notes', 'note', 'notebook', 'write', 'journal'] },
  { emoji: '💊', keywords: ['pill', 'medicine', 'meds'] },
  { emoji: '🩺', keywords: ['doctor', 'stethoscope', 'scan', 'health'] },
  { emoji: '🌡️', keywords: ['temperature', 'thermometer', 'fever'] },
  { emoji: '🗓️', keywords: ['calendar', 'appointment', 'schedule'] },
  { emoji: '🏠', keywords: ['house', 'home'] },
  { emoji: '🛁', keywords: ['bath'] },
  { emoji: '🚿', keywords: ['shower'] },
  { emoji: '🛒', keywords: ['shopping', 'cart', 'groceries'] },
  { emoji: '🛍️', keywords: ['shopping-bag', 'bag', 'errands'] },
  { emoji: '💼', keywords: ['briefcase', 'work', 'job'] },
  { emoji: '💻', keywords: ['laptop', 'computer'] },
  { emoji: '📞', keywords: ['phone', 'call'] },
  { emoji: '🚗', keywords: ['car', 'travel', 'drive'] },
  { emoji: '🚌', keywords: ['bus'] },
  { emoji: '🚆', keywords: ['train'] },
  { emoji: '✈️', keywords: ['plane', 'flight'] },
  { emoji: '✨', keywords: ['sparkles', 'self care'] },
  { emoji: '🙂', keywords: ['smile', 'good mood'] },
  { emoji: '☹️', keywords: ['frown', 'low mood'] },
  { emoji: '🎁', keywords: ['gift'] },
  { emoji: '📷', keywords: ['camera', 'photo'] },
  { emoji: '🐾', keywords: ['paw', 'pet'] },
  { emoji: '🐶', keywords: ['dog'] },
  { emoji: '🐱', keywords: ['cat'] },
  { emoji: '🐟', keywords: ['fish'] },
  { emoji: '🐦', keywords: ['bird'] },
  { emoji: '🐰', keywords: ['rabbit'] },
];

const exactEmojiByKey = {
  ambulance: '🚑',
  pill: '💊',
  'pill-bottle': '💊',
  stethoscope: '🩺',
  thermometer: '🌡️',
  toilet: '💩',
  droplet: '💧',
  dumbbell: '🏋️',
  bike: '🚴',
  'train-front': '🚆',
  'car-front': '🚗',
  bus: '🚌',
  plane: '✈️',
  'alarm-clock': '⏰',
  'calendar-check': '🗓️',
  'calendar-heart': '🗓️',
  'heart-pulse': '💓',
  heart: '❤️',
  coffee: '☕',
  pizza: '🍕',
  apple: '🍎',
  salad: '🥗',
  sandwich: '🥪',
  soup: '🍲',
  shower: '🚿',
};

const exactEmojiByTag = {
  ambulance: '🚑',
  emergency: '🚑',
  medical: '🩺',
  healthcare: '🩺',
  hospital: '🏥',
  toilet: '💩',
  bathroom: '💩',
  fitness: '🏋️',
  workout: '🏋️',
  transport: '🚗',
  vehicle: '🚗',
  meal: '🍽️',
  pasta: '🍝',
};

const categoryEmojiFallback = {
  food: '🍽️',
  health: '🩺',
  body: '💩',
  exercise: '🏋️',
  travel: '🚗',
  home: '🏠',
  work: '💼',
  mood: '✨',
  general: '🏷️',
};

function humanize(key) {
  return key
    .split('-')
    .map((part) => part.length === 1 ? part.toUpperCase() : part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function tokenize(key, tags) {
  return Array.from(
    new Set(
      [key, ...key.split('-'), ...tags]
        .flatMap((entry) => entry.toLowerCase().split(/[^a-z0-9]+/g))
        .filter(Boolean),
    ),
  );
}

function matchesKeyword(tokens, keyword) {
  const normalizedKeyword = keyword.toLowerCase().trim();
  if (!normalizedKeyword) {
    return false;
  }
  if (normalizedKeyword.includes(' ')) {
    return tokens.join(' ').includes(normalizedKeyword);
  }
  return tokens.some((token) => token === normalizedKeyword);
}

function findCategory(tokens) {
  for (const matcher of categoryMatchers) {
    if (matcher.keywords.some((keyword) => matchesKeyword(tokens, keyword))) {
      return matcher.category;
    }
  }
  return 'general';
}

function findEmoji(key, tags, tokens, category) {
  if (exactEmojiByKey[key]) {
    return exactEmojiByKey[key];
  }
  for (const tag of tags) {
    const normalizedTag = String(tag).toLowerCase().trim();
    if (exactEmojiByTag[normalizedTag]) {
      return exactEmojiByTag[normalizedTag];
    }
  }
  for (const matcher of emojiMatchers) {
    if (matcher.keywords.some((keyword) => matchesKeyword(tokens, keyword))) {
      return matcher.emoji;
    }
  }
  return categoryEmojiFallback[category] ?? '🏷️';
}

const [tagsRaw, iconNodesRaw] = await Promise.all([
  fs.readFile(tagsPath, 'utf8'),
  fs.readFile(iconNodesPath, 'utf8'),
]);

const tags = JSON.parse(tagsRaw);
const iconNodes = JSON.parse(iconNodesRaw);

const catalog = Object.keys(iconNodes)
  .sort((left, right) => left.localeCompare(right))
  .map((key) => {
    const iconTags = Array.isArray(tags[key]) ? tags[key] : [];
    const label = humanize(key);
    const tokens = tokenize(key, [label, ...iconTags]);
    const category = findCategory(tokens);
    return {
      key,
      label,
      emoji: findEmoji(key, iconTags, tokens, category),
      keywords: Array.from(new Set([...iconTags, category])),
      category,
    };
  });

await fs.mkdir(path.dirname(outputPath), { recursive: true });
await fs.writeFile(outputPath, JSON.stringify(catalog, null, 2) + '\n', 'utf8');
console.log(`Wrote ${catalog.length} icons to ${outputPath}`);
