var express = require('express');
var bodyParser = require('body-parser');
var mysql = require('mysql');
var config = require('./config');

var app = express();
var pool = mysql.createPool(config.db);
app.use(bodyParser.json());
app.use(express.static('public'));

// BR-1: order total = sum(qty * unit_price), minus 10% when coupon SPRING and subtotal >= 100, rounded half-up to 2 dp
function quote(items, coupon) {
  var subtotal = items.reduce(function (s, i) { return s + i.qty * i.unit_price; }, 0);
  var discount = (coupon === 'SPRING' && subtotal >= 100) ? subtotal * 0.10 : 0;
  return Math.round((subtotal - discount) * 100) / 100;
}

// BR-2: customers only see their own orders (by ?customer=), newest first, 20 per page
app.get('/api/orders', function (req, res) {
  var page = parseInt(req.query.page || '1', 10);
  // VULN (fixture): string-built SQL
  var sql = "SELECT id, customer_id, status, total, created_at FROM orders WHERE customer_id = " + req.query.customer +
            " ORDER BY created_at DESC LIMIT " + ((page - 1) * 20) + ",20";
  pool.query(sql, function (err, rows) {
    if (err) return res.status(500).json({ error: 'db' });
    res.json({ page: page, orders: rows });
  });
});

app.post('/api/orders/quote', function (req, res) {
  if (!Array.isArray(req.body.items) || req.body.items.length === 0) return res.status(400).json({ error: 'items required' });
  res.json({ total: quote(req.body.items, req.body.coupon) });
});

// BR-3: an order can be cancelled only while status is NEW; cancelling twice is a no-op 409
app.post('/api/orders/:id/cancel', function (req, res) {
  pool.query("UPDATE orders SET status = 'CANCELLED' WHERE id = ? AND status = 'NEW'", [req.params.id], function (err, r) {
    if (err) return res.status(500).json({ error: 'db' });
    if (r.affectedRows === 0) return res.status(409).json({ error: 'not cancellable' });
    res.json({ id: Number(req.params.id), status: 'CANCELLED' });
  });
});

if (require.main === module) app.listen(config.port);
module.exports = { app: app, quote: quote };
