// Returns the items of one page. Page numbers start at 1.
export function page(items, number, size) {
  const start = number * size;
  return items.slice(start, start + size);
}
