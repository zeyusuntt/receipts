// Keep every pytest name intact. Only repository and pytest separators wrap.
export function NodeText({text, short = false}: {text: string; short?: boolean}) {
  const value = short ? text.split('::').slice(-2).join('::') : text;
  return <span style={{wordBreak: 'normal', overflowWrap: 'normal'}}>
    {value.split(/(\s+)/).map((token, i) => /\s/u.test(token) ? token : <span key={i}>
      {token.split(/(?<=::|\/)/).map((part, j) => <span key={j}>
        <span style={{whiteSpace: 'nowrap'}}>{part}</span>{/(::|\/)$/u.test(part) ? '\u200B' : null}
      </span>)}
    </span>)}
  </span>;
}
