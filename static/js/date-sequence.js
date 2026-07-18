/* Sequential/chronological date boxes (#40).
   Wherever the four-date sequence appears — Travel In -> Start -> End ->
   Travel Out — enforce Travel In <= Start <= End <= Travel Out:
     * each box's `min` is the nearest earlier box that has a value, so you
       can't pick an out-of-order date and the picker opens at the valid range;
     * focusing an empty box defaults it to the nearest earlier date (Larry's
       "open to the next available valid date").
   Groups are scoped to a single row/form so rows never cross-wire. */
(function () {
  var ORDER = ['travel_in_date', 'start_date', 'end_date', 'travel_out_date'];
  var SEL = ORDER.map(function (n) { return 'input[name="' + n + '"]'; }).join(',');

  function wire(root) {
    var seenScopes = [];
    root.querySelectorAll(SEL).forEach(function (inp) {
      var scope = inp.closest('tr') || inp.closest('form') || root;
      if (seenScopes.indexOf(scope) !== -1) return;
      seenScopes.push(scope);

      var boxes = ORDER
        .map(function (n) { return scope.querySelector('input[name="' + n + '"]'); })
        .filter(Boolean);
      if (boxes.length < 2) return;

      function priorValue(i) {
        for (var j = i - 1; j >= 0; j--) { if (boxes[j].value) return boxes[j].value; }
        return '';
      }
      function applyMins() {
        for (var i = 1; i < boxes.length; i++) { boxes[i].min = priorValue(i); }
      }

      boxes.forEach(function (b, i) {
        b.addEventListener('change', applyMins);
        b.addEventListener('focus', function () {
          applyMins();
          if (!b.value) {
            var pv = priorValue(i);
            if (pv) b.value = pv;   // default an opened empty box to the next valid date
          }
        });
      });
      applyMins();
    });
  }

  document.addEventListener('DOMContentLoaded', function () { wire(document); });
})();
