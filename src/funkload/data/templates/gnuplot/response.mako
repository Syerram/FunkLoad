<%def name="labels(use_x_labels, cols)">\
% if use_x_labels:
${cols}:xticlabels(1)\
% else:
1:${cols}\
% endif
</%def>

set output "${image_path}"
set terminal png size ${chart_size[0]},${chart_size[1]}
set grid
set bars 5.0
set title "${title}"
set xlabel "Concurrent Users"
set ylabel "Duration (s)"
set grid back
set style fill solid .25

% if not use_xticlabels:
set xrange [0:${maxCVUs+1}]
% endif

% if has_error:
set format x ""
set multiplot
unset title
unset xlabel
set size 1, 0.7
set origin 0, 0.3
set lmargin 5
set bmargin 0
% endif

plot "${data_path}" u ${labels(use_xticlabels, '8:8:10:9')} t "med/p90/p95" w candlesticks lt 1 lw 1 whiskerbars 0.5, "" u ${labels(use_xticlabels, '7:4:8:8')} w candlesticks lt 2 lw 1 t "min/p10/med" whiskerbars 0.5, "" u 1:5 t "avg" w lines lt 3 lw 2

% if has_error:
set format x "%% g"
set bmargin 3
set autoscale y
set style fill solid .25
set size 1.0, 0.3
set xlabel "Concurrent Users"
set ylabel "%% errors"
set origin 0.0, 0.0
plot "${data_path}" u ${labels(use_xticlabels, '3')} w linespoints lt 1 lw 2 t "%%%% Errors"
unset multiplot
set size 1.0, 1.0
% endif