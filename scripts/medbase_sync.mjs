// Télécharge la liste MedBase et écrit data/medbase-prix.json (lu automatiquement par Pharmalik).
// La clé API vient du secret GitHub MEDBASE_API_KEY : elle n'est jamais écrite dans un fichier.
import fs from 'node:fs';
import crypto from 'node:crypto';
const BASE = 'https://api.medbase.ma/api/v1';
const KEY = process.env.MEDBASE_API_KEY;
if (!KEY) { console.error('MEDBASE_API_KEY manquante (Settings > Secrets and variables > Actions).'); process.exit(1); }
const OUT = 'data/medbase-prix.json';
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function get(path, tries = 6) {
  for (let i = 0; i < tries; i++) {
    const r = await fetch(BASE + path, { headers: { 'X-API-Key': KEY, Accept: 'application/json' } });
    if (r.status === 429 || r.status >= 500) { await sleep(2000 * (i + 1)); continue; }
    if (!r.ok) throw new Error(`MedBase ${r.status} sur ${path} (request ${r.headers.get('x-request-id')})`);
    return r.json();
  }
  throw new Error('MedBase indisponible : trop de tentatives sur ' + path);
}

const items = [];
let cursor = null, limit = 200;
for (let guard = 0; guard < 1000; guard++) {
  let j;
  try { j = await get(`/drugs/list?limit=${limit}` + (cursor ? `&cursor=${encodeURIComponent(cursor)}` : '')); }
  catch (e) { if (/ 422 /.test(e.message) && limit > 50) { limit = 100; guard--; continue; } throw e; }
  for (const x of (j.data || [])) items.push({
    id: x.id, name: x.name, dosage: x.dosage, form: x.form, package: x.package,
    ppv: x.ppv, ph: x.ph, marketing_status: x.marketing_status, dci: x.dci, atc: x.atc, laboratory: x.laboratory,
  });
  const m = j.meta || {};
  cursor = m.next_cursor || null;
  console.log(`${items.length}${m.total ? ' / ' + m.total : ''}`);
  if (!cursor || m.has_more === false) break;
}

// Garde-fou : ne jamais écraser un bon fichier par une liste incomplète.
let prev = 0;
try { prev = JSON.parse(fs.readFileSync(OUT, 'utf8')).count || 0; } catch {}
if (items.length < 100 || (prev && items.length < prev * 0.9)) {
  console.error(`Liste suspecte (${items.length} contre ${prev} avant) : fichier NON modifié.`);
  process.exit(1);
}
items.sort((a, b) => String(a.id).localeCompare(String(b.id)));
fs.mkdirSync('data', { recursive: true });
// Signature ECDSA P-256 : la cle privee vient du secret MEDBASE_SIGN_KEY ; l'app ne fait confiance qu'aux fichiers signes.
const SK = process.env.MEDBASE_SIGN_KEY;
if (!SK) { console.error('MEDBASE_SIGN_KEY manquante : fichier NON publie.'); process.exit(1); }
const hex = crypto.createHash('sha256').update(JSON.stringify(items)).digest('hex');
const sig = crypto.sign('sha256', Buffer.from('MB1|' + items.length + '|' + hex), { key: SK, dsaEncoding: 'ieee-p1363' }).toString('base64');
fs.writeFileSync(OUT, JSON.stringify({ source: 'MedBase', count: items.length, items, sig }));
console.log('OK', items.length, 'médicaments');
