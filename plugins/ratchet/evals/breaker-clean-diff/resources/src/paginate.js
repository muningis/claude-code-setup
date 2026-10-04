// Returns the items of one page. Page numbers start at 1.
export function page(items, number, size) {
  if (!Number.isInteger(number) || number < 1) throw new RangeError("page number must be 1 or more");
  if (!Number.isInteger(size) || size < 1) throw new RangeError("page size must be 1 or more");
  const start = (number - 1) * size;
  return items.slice(start, start + size);
}
