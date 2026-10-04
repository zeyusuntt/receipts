import {readFileSync, writeFileSync} from 'node:fs';
import QRCode from 'qrcode';

const story = JSON.parse(readFileSync(new URL('../src/content/story.json', import.meta.url), 'utf8'));
const url = story.presentation.close.site_url;
const svg = await QRCode.toString(url, {type: 'svg', errorCorrectionLevel: 'M', margin: 4, color: {dark: '#12161C', light: '#FFFEFA'}});
writeFileSync(new URL('../public/receipts-qr.svg', import.meta.url), svg);
console.log(`Generated offline QR for ${url}`);
