function storageKey(actor) {
  return `certificate-console:pending:v1:${JSON.stringify([actor.tenant, actor.email])}`;
}

function valid(operation) {
  return operation && typeof operation.key === 'string' && operation.key.trim().length > 0 && operation.key.length <= 200
    && operation.payload && Object.keys(operation.payload).length === 1
    && Number.isSafeInteger(operation.payload.course_id) && operation.payload.course_id > 0;
}

export function loadPending(actor, storage = window.sessionStorage) {
  const raw = storage.getItem(storageKey(actor));
  if (raw === null) return null;
  const operation = JSON.parse(raw);
  if (!valid(operation)) throw new Error('Invalid saved operation');
  return operation;
}

export function savePending(actor, operation, storage = window.sessionStorage) {
  if (!valid(operation)) throw new Error('Invalid operation');
  storage.setItem(storageKey(actor), JSON.stringify(operation));
}

export function clearPending(actor, key, storage = window.sessionStorage) {
  if (loadPending(actor, storage)?.key === key) storage.removeItem(storageKey(actor));
}
