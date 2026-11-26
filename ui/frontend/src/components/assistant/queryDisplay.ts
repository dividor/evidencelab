export const capitalizeFollowUp = (query: string) =>
  query.replace(/\p{L}/u, letter => letter.toLocaleUpperCase());
