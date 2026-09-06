declare const jest: { fn?: () => any } | undefined;

const jestRef =
  (typeof jest !== 'undefined' ? jest : undefined) ||
  (globalThis as { jest?: { fn?: () => any } }).jest;
const makeFn = () => {
  if (jestRef?.fn) {
    return jestRef.fn();
  }

  const defaultImpl = () => Promise.resolve({ data: {} });
  let impl = defaultImpl;
  const onceQueue: Array<(...args: any[]) => any> = [];

  const fn: any = (...args: any[]) => {
    const next = onceQueue.shift() ?? impl;
    return next(...args);
  };

  fn.mockResolvedValue = (value: any) => {
    impl = () => Promise.resolve(value);
    return fn;
  };
  fn.mockResolvedValueOnce = (value: any) => {
    onceQueue.push(() => Promise.resolve(value));
    return fn;
  };
  fn.mockRejectedValue = (value: any) => {
    impl = () => Promise.reject(value);
    return fn;
  };
  fn.mockRejectedValueOnce = (value: any) => {
    onceQueue.push(() => Promise.reject(value));
    return fn;
  };
  fn.mockImplementation = (nextImpl: (...args: any[]) => any) => {
    impl = nextImpl;
    return fn;
  };
  fn.mockImplementationOnce = (nextImpl: (...args: any[]) => any) => {
    onceQueue.push(nextImpl);
    return fn;
  };
  fn.mockClear = () => {
    onceQueue.length = 0;
    impl = defaultImpl;
  };

  return fn;
};

// Mirrors axios's cancellation contract: a request aborted through its
// AbortSignal rejects with an error carrying `__CANCEL__`, which
// `axios.isCancel` recognises.
class CanceledError extends Error {
  __CANCEL__ = true;

  constructor(message = 'canceled') {
    super(message);
    this.name = 'CanceledError';
  }
}

const axiosMock = {
  get: makeFn(),
  put: makeFn(),
  post: makeFn(),
  patch: makeFn(),
  delete: makeFn(),
  defaults: {
    withCredentials: false,
    headers: { common: {}, get: {}, post: {}, put: {}, patch: {}, delete: {} },
  },
  interceptors: {
    request: { use: makeFn(), eject: makeFn() },
    response: { use: makeFn(), eject: makeFn() },
  },
  create: () => axiosMock,
  isAxiosError: () => false,
  isCancel: (value: unknown) =>
    !!value && (value as { __CANCEL__?: boolean }).__CANCEL__ === true,
  CanceledError,
};

export default axiosMock;
