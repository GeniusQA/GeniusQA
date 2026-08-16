const crypto = require('crypto');

const [body, timestamp, apiSecret] = process.argv.slice(2);
const signString = body + '|' + timestamp;
const signature = crypto.createHmac('sha256', apiSecret)
  .update(signString)
  .digest('hex');

console.log(signature);  