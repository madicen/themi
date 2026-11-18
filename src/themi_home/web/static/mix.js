// CK15a: a mix (themi_home/music_mix.py) played live with Web Audio, the way
// tools/make_loops.py renders one with ffmpeg: chords as a sine with a quieter octave and a
// soft attack, fading after each strike; a soft kick and hat for lofi; noise through filters
// with a slow swell; an echo. No library: the page's CSP stays 'self'.
(function () {
  "use strict";
  var Ctx = window.AudioContext || window.webkitAudioContext;
  var STEPS = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
  var AHEAD = 0.3;  // seconds scheduled ahead of the clock
  var TICK = 60;    // ms between looks ahead

  function hz(note) {
    var semis = STEPS[note[0]] + (note.indexOf("#") > 0 ? 1 : 0) + 12 * (Number(note[note.length - 1]) - 4);
    return 261.6256 * Math.pow(2, semis / 12);
  }

  // What happens in [from, to) seconds after the start: each strike with its chord, and the
  // beat. Pure, so a test can read it without any sound.
  function events(mix, from, to) {
    var out = [];
    var bar = mix.beats * 60 / mix.bpm, beat = bar / mix.beats;
    if (mix.chords && mix.chords.length) {
      var strike = bar / mix.strikes;
      for (var k = Math.max(0, Math.ceil(from / strike - 1e-9)); k * strike < to; k++) {
        out.push({ at: k * strike, kind: "strike", chord: Math.floor(k / mix.strikes) % mix.chords.length, length: strike });
      }
    }
    if (mix.beat) {
      for (var j = Math.max(0, Math.ceil(from / (2 * beat) - 1e-9)); j * 2 * beat < to; j++) {
        out.push({ at: j * 2 * beat, kind: "kick", length: 2 * beat });
      }
      for (var h = Math.max(0, Math.ceil((from - beat / 2) / beat - 1e-9)); beat / 2 + h * beat < to; h++) {
        out.push({ at: beat / 2 + h * beat, kind: "hat", length: beat });
      }
    }
    out.sort(function (a, b) { return a.at - b.at; });
    return out;
  }

  function noiseBuffer(ctx, color, seconds) {
    var length = Math.floor(ctx.sampleRate * seconds);
    var buffer = ctx.createBuffer(1, length, ctx.sampleRate), data = buffer.getChannelData(0);
    var b0 = 0, b1 = 0, b2 = 0, b3 = 0, b4 = 0, b5 = 0, b6 = 0, last = 0;
    for (var i = 0; i < length; i++) {
      var white = Math.random() * 2 - 1;
      if (color === "pink") {  // Paul Kellet's filter
        b0 = 0.99886 * b0 + white * 0.0555179; b1 = 0.99332 * b1 + white * 0.0750759;
        b2 = 0.96900 * b2 + white * 0.1538520; b3 = 0.86650 * b3 + white * 0.3104856;
        b4 = 0.55000 * b4 + white * 0.5329522; b5 = -0.7616 * b5 - white * 0.0168980;
        data[i] = (b0 + b1 + b2 + b3 + b4 + b5 + b6 + white * 0.5362) * 0.11;
        b6 = white * 0.115926;
      } else if (color === "brown") {
        last = (last + 0.02 * white) / 1.02;
        data[i] = last * 3.5;
      } else {
        data[i] = white;
      }
    }
    return buffer;
  }

  function filter(ctx, type, frequency) {
    var f = ctx.createBiquadFilter();
    f.type = type;
    f.frequency.value = frequency;
    f.Q.value = Math.SQRT1_2;
    return f;
  }

  function gain(ctx, value) {
    var g = ctx.createGain();
    g.gain.value = value;
    return g;
  }

  // noise through its filters, its swell and its gain, into `to`
  function noise(ctx, n, to, stops) {
    var source = ctx.createBufferSource();
    source.buffer = noiseBuffer(ctx, n.color, 8);
    source.loop = true;
    var node = source, level = gain(ctx, n.amplitude * n.gain);
    if (n.highpass) { var hp = filter(ctx, "highpass", n.highpass); node.connect(hp); node = hp; }
    if (n.lowpass) { var lp = filter(ctx, "lowpass", n.lowpass); node.connect(lp); node = lp; }
    if (n.swell_hz) {
      var swell = gain(ctx, 1 - n.swell_depth / 2), lfo = ctx.createOscillator(), depth = gain(ctx, n.swell_depth / 2);
      lfo.frequency.value = n.swell_hz;
      lfo.connect(depth).connect(swell.gain);
      lfo.start();
      stops.push(lfo);
      node.connect(swell); node = swell;
    }
    node.connect(level).connect(to);
    source.start();
    stops.push(source);
  }

  function play(mix, options) {
    if (!Ctx) return null;
    options = options || {};
    var ctx = options.context || new Ctx();
    var out = gain(ctx, options.volume === undefined ? 0.5 : options.volume);
    out.connect(ctx.destination);
    var stops = [], timer = null, started = ctx.currentTime + 0.05, done = 0;
    var hat = noiseBuffer(ctx, "white", 0.2);
    var keys = filter(ctx, "lowpass", mix.tone);
    if (mix.echoes && mix.echoes.length) {
      keys.connect(gain(ctx, 0.8 * mix.echo_out)).connect(out);
      mix.echoes.forEach(function (e) {
        var delay = ctx.createDelay(1);
        delay.delayTime.value = e[0] / 1000;
        keys.connect(delay).connect(gain(ctx, 0.8 * e[1] * mix.echo_out)).connect(out);
      });
    } else {
      keys.connect(out);
    }
    if (mix.noise) noise(ctx, mix.noise, out, stops);
    var player = { mix: mix, context: ctx, playing: true, scheduled: [] };

    function strike(at, chord, length) {
      var env = ctx.createGain(), end = at + length;
      env.gain.setValueAtTime(0, at);
      env.gain.setTargetAtTime(mix.level, at, 1 / 60);
      env.gain.setTargetAtTime(0, at + 0.05, 1 / mix.decay);
      env.gain.setTargetAtTime(0, end - 0.02, 0.005);  // no click at the next strike
      env.connect(keys);
      mix.chords[chord].forEach(function (note) {
        var f = hz(note);
        [[f, 1], [2 * f, 0.25]].forEach(function (part) {
          var osc = ctx.createOscillator(), level = gain(ctx, part[1]);
          osc.frequency.value = part[0];
          osc.connect(level).connect(env);
          osc.start(at);
          osc.stop(end);
        });
      });
    }
    function kick(at, length) {
      var osc = ctx.createOscillator(), env = ctx.createGain();
      osc.frequency.value = 52;
      env.gain.setValueAtTime(0.5, at);
      env.gain.setTargetAtTime(0, at, 1 / 14);
      osc.connect(env).connect(keys);
      osc.start(at);
      osc.stop(at + length);
    }
    function tap(at) {
      var source = ctx.createBufferSource(), env = ctx.createGain();
      source.buffer = hat;
      env.gain.setValueAtTime(0.04, at);
      env.gain.setTargetAtTime(0, at, 1 / 45);
      source.connect(env).connect(keys);
      source.start(at);
    }
    function tick() {
      if (!player.playing) return;
      var upTo = Math.max(done, ctx.currentTime - started + AHEAD);
      events(mix, done, upTo).forEach(function (e) {
        var at = started + e.at;
        if (e.kind === "strike") {
          strike(at, e.chord, e.length);
          player.scheduled.push(e.chord);
          if (player.scheduled.length > 64) player.scheduled.shift();
        } else if (e.kind === "kick") kick(at, e.length);
        else tap(at);
      });
      done = upTo;
      timer = setTimeout(tick, TICK);
    }

    player.setVolume = function (v) { out.gain.setTargetAtTime(v, ctx.currentTime, 0.02); };
    player.stop = function () {
      if (!player.playing) return;
      player.playing = false;
      clearTimeout(timer);
      out.gain.setTargetAtTime(0, ctx.currentTime, 0.03);
      setTimeout(function () {
        stops.forEach(function (s) { try { s.stop(); } catch (e) { /* already stopped */ } });
        out.disconnect();
        if (!options.context && ctx.close) ctx.close().then(function () {}, function () {});
      }, 200);
    };
    if (ctx.state === "suspended" && ctx.resume) ctx.resume().then(function () {}, function () {});
    tick();
    return player;
  }

  window.themiMix = { supported: !!Ctx, play: play, events: events, hz: hz };
})();
