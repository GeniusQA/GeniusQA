const cp = require('child_process');
const r = cp.spawnSync('npx', ['--version'], { encoding: 'utf8' });
console.log('status=' + r.status);
console.log('error=' + (r.error && r.error.message));
console.log('stdout=' + (r.stdout || '').slice(0, 120));
console.log('stderr=' + (r.stderr || '').slice(0, 200));
