const cp = require('child_process');
for (const cmd of ['npx', 'npx.cmd', 'npm', 'npm.cmd']) {
  const r = cp.spawnSync(cmd, ['--version'], { encoding: 'utf8' });
  console.log(cmd + ' => status=' + r.status + ' err=' + (r.error && r.error.message) + ' out=' + (r.stdout || '').trim().slice(0, 40));
}
