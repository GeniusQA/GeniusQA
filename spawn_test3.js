const cp = require('child_process');
console.log('platform=' + process.platform);
console.log('PATHEXT=' + JSON.stringify(process.env.PATHEXT));
console.log('PATH has Node.js=' + (process.env.PATH || '').includes('D:\\Node.js'));
try { console.log('execSync npx: ' + cp.execSync('npx --version', { encoding: 'utf8' }).trim()); }
catch (e) { console.log('execSync npx ERR: ' + e.message); }
try { console.log('execSync npx.cmd: ' + cp.execSync('npx.cmd --version', { encoding: 'utf8' }).trim()); }
catch (e) { console.log('execSync npx.cmd ERR: ' + e.message); }
const r = cp.spawnSync('npx.cmd', ['--version'], { shell: true, encoding: 'utf8' });
console.log('spawnSync shell npx.cmd: status=' + r.status + ' err=' + (r.error && r.error.message) + ' out=' + (r.stdout || '').trim());
