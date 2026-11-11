.pragma library

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

// Presentation only: history, requests and editing keep the original Markdown.
function prepare(source) {
    // Disable media before parsing code, so incomplete or ambiguous Markdown
    // cannot bypass this rule. Image labels/links remain; attachments own media.
    const lines = source.replace(/!\[/g, "[").replace(/<img\b[^>]*>/gi, "").replace(/\r\n?/g, "\n").split("\n");
    let result = "";
    let pending = "";
    let fence = "";
    let fenceLength = 0;
    for (let index = 0; index < lines.length; index++) {
        const line = lines[index];
        const complete = line + (index < lines.length - 1 ? "\n" : "");
        const marker = /^ {0,3}(?:> ?)*(`{3,}|~{3,})(.*)$/.exec(line);
        if (fence) {
            if (marker && marker[1][0] === fence && marker[1].length >= fenceLength && !marker[2].trim())
                fence = "";
            result += complete;
            continue;
        }
        const opensFence = marker && (marker[1][0] === "~" || !marker[2].includes("`"));
        if (opensFence || /^( {4}|\t)/.test(line)) {
            result += prose(pending) + complete;
            pending = "";
        } else {
            pending += complete;
        }
        if (opensFence) {
            fence = marker[1][0];
            fenceLength = marker[1].length;
        }
    }
    return result + prose(pending);
}
