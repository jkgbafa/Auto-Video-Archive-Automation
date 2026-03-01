#!/usr/bin/env node
/**
 * Internxt Bridge — Node.js wrapper for Internxt SDK operations.
 * Called by Python's internxt_client.py for auth, list, download.
 *
 * Uses the official @internxt/sdk which handles OPAQUE auth,
 * encryption/decryption, and all the crypto complexity.
 *
 * Usage:
 *   node internxt_bridge.js login
 *   node internxt_bridge.js list [folder-uuid]
 *   node internxt_bridge.js download <file-uuid> <dest-dir>
 *   node internxt_bridge.js info
 */

const { execSync, spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const TOKEN_FILE = path.join(__dirname, 'internxt_token.json');

// Config
const DRIVE_API = 'https://gateway.internxt.com/drive';
const HEADERS = {
  'Content-Type': 'application/json; charset=utf-8',
  'internxt-version': '1.5.6',
  'internxt-client': 'internxt-cli',
};

// ---------- Token management ----------
function loadToken() {
  try {
    if (fs.existsSync(TOKEN_FILE)) {
      return JSON.parse(fs.readFileSync(TOKEN_FILE, 'utf8'));
    }
  } catch (e) {}
  return null;
}

function saveToken(token, user) {
  fs.writeFileSync(TOKEN_FILE, JSON.stringify({
    token,
    user,
    saved_at: new Date().toISOString(),
  }, null, 2));
}

// ---------- CLI-based login (uses internxt CLI which handles crypto) ----------
async function loginViaCLI() {
  const email = process.env.INTERNXT_EMAIL || 'ytoffice2023@gmail.com';
  const password = process.env.INTERNXT_PASSWORD || 'SeeMe123!';

  console.error('[Internxt Bridge] Logging in via CLI...');
  const result = spawnSync('npx', [
    'internxt', 'login-legacy',
    '--email', email,
    '--password', password,
  ], {
    timeout: 60000,
    encoding: 'utf8',
    stdio: ['pipe', 'pipe', 'pipe'],
  });

  if (result.status === 0) {
    console.error('[Internxt Bridge] CLI login successful');
    return true;
  }

  console.error(`[Internxt Bridge] CLI login failed: ${result.stderr || result.stdout}`);
  return false;
}

// ---------- API calls using token ----------
async function apiGet(endpoint, token) {
  const response = await fetch(`${DRIVE_API}${endpoint}`, {
    method: 'GET',
    headers: { ...HEADERS, 'Authorization': `Bearer ${token}` },
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`API ${response.status}: ${text.substring(0, 200)}`);
  }

  return response.json();
}

// ---------- List folder ----------
async function listFolder(folderUuid, token) {
  let allFiles = [];
  let allFolders = [];
  let offset = 0;
  const limit = 50;

  // Paginate through files
  while (true) {
    const data = await apiGet(`/folders/content/${folderUuid}/files?limit=${limit}&offset=${offset}&sort=plainName&order=ASC`, token);
    const files = data.files || [];
    allFiles = allFiles.concat(files);
    if (files.length < limit) break;
    offset += limit;
  }

  // Get subfolders
  offset = 0;
  while (true) {
    const data = await apiGet(`/folders/content/${folderUuid}/folders?limit=${limit}&offset=${offset}&sort=plainName&order=ASC`, token);
    const folders = data.folders || [];
    allFolders = allFolders.concat(folders);
    if (folders.length < limit) break;
    offset += limit;
  }

  return {
    files: allFiles.map(f => ({
      name: f.plainName + (f.type ? '.' + f.type : ''),
      uuid: f.uuid,
      fileId: f.fileId,
      size: parseInt(f.size || '0'),
      is_folder: false,
      bucket: f.bucket,
      createdAt: f.createdAt,
      updatedAt: f.updatedAt,
      status: f.status,
    })),
    folders: allFolders.map(f => ({
      name: f.plainName,
      uuid: f.uuid,
      is_folder: true,
      status: f.status,
    })),
  };
}

// ---------- Download via CLI ----------
async function downloadFile(fileUuid, destDir) {
  console.error(`[Internxt Bridge] Downloading ${fileUuid} to ${destDir}`);
  const result = spawnSync('npx', [
    'internxt', 'download-file',
    '--id', fileUuid,
    '--directory', destDir,
    '-x',  // non-interactive
  ], {
    timeout: 7200000,  // 2 hours
    encoding: 'utf8',
    stdio: ['pipe', 'pipe', 'pipe'],
  });

  if (result.status === 0) {
    console.error('[Internxt Bridge] Download complete');
    return true;
  }
  console.error(`[Internxt Bridge] Download failed: ${result.stderr || result.stdout}`);
  return false;
}

// ---------- Main ----------
async function main() {
  const cmd = process.argv[2];

  if (!cmd || cmd === 'help') {
    console.log(JSON.stringify({
      commands: ['login', 'list', 'download', 'info'],
      usage: 'node internxt_bridge.js <command> [args]',
    }));
    return;
  }

  if (cmd === 'login') {
    const ok = await loginViaCLI();
    console.log(JSON.stringify({ success: ok }));
    return;
  }

  if (cmd === 'info') {
    // Get user config from CLI
    const result = spawnSync('npx', ['internxt', 'config'], {
      timeout: 15000, encoding: 'utf8',
    });
    console.log(JSON.stringify({
      success: result.status === 0,
      output: result.stdout,
    }));
    return;
  }

  if (cmd === 'list') {
    const folderUuid = process.argv[3];
    const tokenData = loadToken();

    if (!tokenData || !tokenData.token) {
      // Try to get token from CLI config
      console.log(JSON.stringify({ error: 'No token. Run: node internxt_bridge.js login' }));
      return;
    }

    try {
      const rootUuid = folderUuid || tokenData.user?.rootFolderId;
      if (!rootUuid) {
        console.log(JSON.stringify({ error: 'No folder UUID specified and no root folder ID saved' }));
        return;
      }

      const result = await listFolder(rootUuid, tokenData.token);
      console.log(JSON.stringify(result));
    } catch (e) {
      console.log(JSON.stringify({ error: e.message }));
    }
    return;
  }

  if (cmd === 'download') {
    const fileUuid = process.argv[3];
    const destDir = process.argv[4] || '/tmp';

    if (!fileUuid) {
      console.log(JSON.stringify({ error: 'Missing file UUID' }));
      return;
    }

    const ok = await downloadFile(fileUuid, destDir);
    console.log(JSON.stringify({ success: ok }));
    return;
  }

  console.log(JSON.stringify({ error: `Unknown command: ${cmd}` }));
}

main().catch(e => {
  console.log(JSON.stringify({ error: e.message }));
  process.exit(1);
});
