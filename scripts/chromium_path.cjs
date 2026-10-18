// Prints the path of the @sparticuz/chromium binary (extracts it on first call).
// The CJS build exports the class itself; newer builds put it on .default.
const mod = require('@sparticuz/chromium');
const chromium = mod.default || mod;
chromium.executablePath().then(p => { process.stdout.write(p + '\n'); }).catch(e => { console.error(e); process.exit(1); });
