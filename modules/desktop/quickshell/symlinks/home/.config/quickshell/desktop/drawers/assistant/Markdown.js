.pragma library

// Presentation only: history, requests, editing and Copy keep the original
// Markdown. Top-level fenced code becomes exact plain-text segments; everything
// else is prose for Qt's Markdown renderer, which would otherwise fetch images
// and raw-HTML backgrounds from whatever URL a reply names.

const FENCE = /^( {0,3})((?:> ?)*)(`{3,}|~{3,})(.*)$/;

function opensFence(marker) {
    return !!marker && (marker[3][0] === "~" || !marker[4].includes("`"));
}

function closesFence(marker, fence, length) {
    return !!marker && marker[3][0] === fence && marker[3].length >= length && !marker[4].trim();
}

// Remove everything the renderer could load, one line at a time: image syntax
// and all raw HTML. Only single-line code spans keep their text. Block
// structure cannot be trusted here: a construct this file reads as code but
// the renderer reads as HTML would load its URL.
function neutralize(line) {
    if (!/[<!]/.test(line))
        return line;
    const length = line.length;
    let result = "";
    let index = 0;
    while (index < length) {
        const character = line[index];
        if (character === "\\") {
            result += line.substr(index, 2);
            index += 2;
        } else if (character === "`") {
            let run = 1;
            while (line[index + run] === "`")
                run++;
            // A span closes at the next run of exactly the same length.
            let close = -1;
            for (let search = index + run; search < length; ) {
                if (line[search] !== "`") {
                    search++;
                    continue;
                }
                let size = 1;
                while (line[search + size] === "`")
                    size++;
                if (size === run) {
                    close = search;
                    break;
                }
                search += size;
            }
            const end = close < 0 ? index + run : close + run;
            result += line.slice(index, end);
            index = end;
        } else if (character === "!") {
            let marks = 1;
            while (line[index + marks] === "!")
                marks++;
            // Image labels stay as links; "!![" must not leave a second "![".
            if (line[index + marks] !== "[")
                result += line.substr(index, marks);
            index += marks;
        } else if (character === "<" && /[A-Za-z\/!?]/.test(line[index + 1] || "")) {
            const rest = line.slice(index);
            // Autolinks open only on activation. Replies use <br> inside table
            // cells, where Markdown has no line break of its own.
            const link = /^<https?:\/\/[^\s<>`]+>/i.exec(rest);
            const lineBreak = /^<br\s*\/?>/i.exec(rest);
            if (link) {
                result += link[0];
                index += link[0].length;
            } else if (lineBreak) {
                result += " ";
                index += lineBreak[0].length;
            } else {
                result += "&lt;";
                index++;
            }
        } else {
            result += character;
            index++;
        }
    }
    return result;
}

function text(source) {
    return source.replace(/([^\n]*)\n/g, (_, line) => {
        return (/ {2}$|\\$/.test(line) ? line : line + "  ") + "\n";
    });
}

function prose(source) {
    // Protect complete code spans, including multiline spans, before applying
    // chat line breaks. Unclosed backticks stay ordinary
    // text, as they do in Markdown and while a reply is still streaming.
    const spans = /(^|[^\\`])(`+)(?!`)([\s\S]*?)\2(?!`)/g;
    let result = "";
    let start = 0;
    let match;
    while ((match = spans.exec(source)) !== null) {
        const codeStart = match.index + match[1].length;
        result += text(source.slice(start, codeStart)) + source.slice(codeStart, spans.lastIndex);
        start = spans.lastIndex;
    }
    return result + text(source.slice(start));
}

// One prose segment as Markdown for the renderer: neutralized, with chat line
// breaks outside code. Quoted and nested fences stay here, since only the
// renderer knows their container.
function display(source) {
    const lines = source.split("\n");
    let result = "";
    let pending = "";
    let fence = "";
    let fenceLength = 0;
    for (let index = 0; index < lines.length; index++) {
        const line = neutralize(lines[index]);
        const complete = line + (index < lines.length - 1 ? "\n" : "");
        const marker = FENCE.exec(line);
        if (fence) {
            if (closesFence(marker, fence, fenceLength))
                fence = "";
            result += complete;
            continue;
        }
        const opens = opensFence(marker);
        if (opens || /^( {4}|\t)/.test(line)) {
            result += prose(pending) + complete;
            pending = "";
        } else {
            pending += complete;
        }
        if (opens) {
            fence = marker[3][0];
            fenceLength = marker[3].length;
        }
    }
    return result + prose(pending);
}

// [{kind: "text", text: Markdown}, {kind: "code", text: exact source}]
function segments(source) {
    const lines = source.replace(/\r\n?/g, "\n").split("\n");
    const result = [];
    let pending = [];
    let code = null;
    let fence = "";
    let fenceLength = 0;
    let indent = 0;

    function pushText() {
        const value = pending.join("\n");
        pending = [];
        if (value.trim())
            result.push({
                kind: "text",
                text: display(value)
            });
    }

    for (const line of lines) {
        const marker = FENCE.exec(line);
        if (code) {
            if (closesFence(marker, fence, fenceLength) && !marker[2]) {
                if (code.length)
                    result.push({
                        kind: "code",
                        text: code.join("\n")
                    });
                code = null;
            } else {
                let strip = 0;
                while (strip < indent && line[strip] === " ")
                    strip++;
                code.push(line.slice(strip));
            }
        } else if (opensFence(marker) && !marker[2]) {
            pushText();
            code = [];
            fence = marker[3][0];
            fenceLength = marker[3].length;
            indent = marker[1].length;
        } else {
            pending.push(line);
        }
    }
    // A reply that is still streaming shows its open block as code already.
    if (code && code.length)
        result.push({
            kind: "code",
            text: code.join("\n")
        });
    pushText();
    return result;
}
