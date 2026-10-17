/* Pure freshness rules, shared by the browser and the small Node checks. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.BirdframeFreshness = factory();
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  function classify(status, now = Date.now(), fetchFailed = false) {
    const checked = typeof status?.checkedAt === 'string' && /(?:Z|[+-]\d\d:\d\d)$/i.test(status.checkedAt) ? Date.parse(status.checkedAt) : NaN;
    const age = (now - checked) / 1000;
    if (!Number.isFinite(age) || age < -120) return {state:'unknown', label:'Recorder status unavailable', detail:'A recent recorder check is not available.'};
    const threshold = Number(status.staleAfterSeconds);
    if (!Number.isFinite(threshold) || threshold < 60) return {state:'unknown', label:'Recorder status unavailable', detail:'The recorder check could not be verified.'};
    if (age >= threshold) return {state:'stale', label:'Recorder not reporting', detail:'Several expected check-ins have been missed. The last published data is still available; the recorder or its connection may be unavailable.'};
    if (fetchFailed) return {state:'unknown', label:'Unable to check recorder', detail:'The latest status could not be fetched. The last successful check is shown.'};
    const states = {
      listening: {state:'online', label:'Recorder online', detail:'Audio capture was healthy at the last check-in.'},
      paused: {state:'paused', label:'Recording paused', detail:'The recorder checked in, but audio capture is paused.'},
      starting: {state:'starting', label:'Recorder starting', detail:'The recorder checked in and is checking its audio stream.'},
      attention: {state:'attention', label:'Recorder needs attention', detail:'The recorder checked in, but audio capture or analysis was not healthy.'},
      unknown: {state:'unknown', label:'Recorder status unavailable', detail:'The publisher checked in without a verified audio status.'},
    };
    return states[status.recorder] || states.unknown;
  }
  function relative(iso, now = Date.now()) {
    const stamp = Date.parse(iso);
    if (!Number.isFinite(stamp)) return 'Unavailable';
    const seconds = Math.max(0, Math.floor((now - stamp) / 1000));
    if (seconds < 60) return 'just now';
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes} min ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours} ${hours === 1 ? 'hour' : 'hours'} ago`;
    const days = Math.floor(hours / 24);
    return `${days} ${days === 1 ? 'day' : 'days'} ago`;
  }
  return {classify, relative};
}));
