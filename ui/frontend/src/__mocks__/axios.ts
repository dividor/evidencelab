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

const axiosMock = {
  get: makeFn(),
  put: makeFn(),
  post: makeFn(),
  patch: makeFn(),
};

export default axiosMock;
