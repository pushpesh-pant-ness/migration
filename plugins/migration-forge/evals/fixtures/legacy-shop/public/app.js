$(function () {
  $('#load').on('click', function () {
    $.getJSON('/api/orders?customer=' + $('#customer').val(), function (data) {
      $('#orders').empty();
      data.orders.forEach(function (o) {
        // VULN (fixture): unescaped HTML injection
        $('#orders').append('<li>#' + o.id + ' ' + o.status + ' $' + o.total + '</li>');
      });
    });
  });
});
