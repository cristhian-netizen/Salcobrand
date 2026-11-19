// State of one image on screen: shimmer while it loads, fade-in when ready, visible error with retry.
// Pure transitions so the component stays a thin wrapper and the behaviour is testable.
export const initial = src => ({src: src || '', phase: src ? 'loading' : 'empty', attempt: 0});

export const loaded = state => state.phase === 'empty' ? state : {...state, phase: 'ready'};

export const failed = state => state.phase === 'ready' || state.phase === 'empty' ? state : {...state, phase: 'error'};

export const retried = state => state.phase === 'error' ? {...state, phase: 'loading', attempt: state.attempt + 1} : state;

// A retry must reach the server again, not the browser's negative cache; the marker never touches the first URL.
export const sourceFor = state => !state.src || !state.attempt || state.src.startsWith('data:') ? state.src
  : state.src + (state.src.includes('?') ? '&' : '?') + 'retry=' + state.attempt;

export const wrapperClass = state => 'sb-img' + (state.phase === 'ready' ? ' is-ready' : state.phase === 'error' ? ' is-error' : ' is-loading');
