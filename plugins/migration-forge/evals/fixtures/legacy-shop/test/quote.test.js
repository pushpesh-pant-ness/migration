var assert = require('assert');
var quote = require('../server').quote;
describe('quote (BR-1)', function () {
  it('applies SPRING at >= 100', function () { assert.strictEqual(quote([{ qty: 2, unit_price: 50 }], 'SPRING'), 90); });
  it('no discount under 100', function () { assert.strictEqual(quote([{ qty: 1, unit_price: 99.99 }], 'SPRING'), 99.99); });
});
