// Prints the path of the @sparticuz/chromium binary (extracts it on first call).
const chromium = require('@sparticuz/chromium').default;
chromium.executablePath().then(p => { process.stdout.write(p + '\n'); }).catch(e => { console.error(e); process.exit(1); });
