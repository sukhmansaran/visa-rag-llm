"use client";

import React from "react";

interface MarkdownMessageProps {
    content: string;
    isStreaming?: boolean;
}

/**
 * Parses inline formatting like **bold**, *italic*, `code`, and [links](url).
 */
function renderInlineFormatting(text: string): React.ReactNode[] {
    // Regex matches:
    // 1. **bold**
    // 2. *italic* or _italic_
    // 3. `inline code`
    // 4. [text](url)
    const regex = /(\*\*[^*]+?\*\*|\*[^*]+?\*|`[^`]+?`|\[[^\]]+?\]\([^)]+?\))/g;
    const parts = text.split(regex);

    return parts.map((part, index) => {
        if (!part) return null;

        // Bold: **text**
        if (part.startsWith("**") && part.endsWith("**") && part.length >= 4) {
            const inner = part.slice(2, -2);
            return (
                <strong key={index} className="font-semibold text-slate-900 dark:text-slate-100">
                    {inner}
                </strong>
            );
        }

        // Italic: *text* (avoiding lone asterisks)
        if (part.startsWith("*") && part.endsWith("*") && part.length >= 2 && !part.startsWith("**")) {
            const inner = part.slice(1, -1);
            return (
                <em key={index} className="italic text-slate-800 dark:text-slate-200">
                    {inner}
                </em>
            );
        }

        // Inline Code: `code`
        if (part.startsWith("`") && part.endsWith("`") && part.length >= 2) {
            const inner = part.slice(1, -1);
            return (
                <code
                    key={index}
                    className="px-1.5 py-0.5 mx-0.5 rounded text-xs font-mono bg-slate-100 dark:bg-slate-800 text-indigo-600 dark:text-indigo-400 border border-slate-200 dark:border-slate-700"
                >
                    {inner}
                </code>
            );
        }

        // Link: [title](url)
        const linkMatch = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
        if (linkMatch) {
            const [, title, href] = linkMatch;
            return (
                <a
                    key={index}
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary hover:underline font-medium inline-flex items-center gap-0.5"
                >
                    {title}
                </a>
            );
        }

        return <React.Fragment key={index}>{part}</React.Fragment>;
    });
}

/**
 * Normalizes text where the LLM compressed bullet points into a single line,
 * e.g. "Some text: * **Item 1**: desc * **Item 2**: desc + Subitem: desc"
 * into separate lines with proper markdown list markers.
 */
function normalizeMarkdownText(rawText: string): string {
    if (!rawText) return "";

    let text = rawText;

    // 1. Break inline asterisks/bullets that follow punctuation or words without a newline:
    // e.g. "...outside of Quebec. * **First-Year..." -> "...outside of Quebec.\n\n* **First-Year..."
    text = text.replace(/([^\n])\s+([*+-]|\d+\.)\s+(\*\*)/g, "$1\n\n$2 $3");

    // 2. Break inline plain bullets:
    // e.g. "...Quebec. * You must..." -> "...Quebec.\n\n* You must..."
    text = text.replace(/([.:;?!])\s+([*+-])\s+([A-Z])/g, "$1\n\n$2 $3");

    return text;
}

export function MarkdownMessage({ content, isStreaming }: MarkdownMessageProps) {
    if (!content) {
        return isStreaming ? (
            <span className="inline-block w-1.5 h-4 ml-0.5 bg-primary animate-pulse rounded-sm align-middle" />
        ) : null;
    }

    const normalized = normalizeMarkdownText(content);
    const lines = normalized.split("\n");

    const elements: React.ReactNode[] = [];
    let currentList: { type: "ul" | "ol"; items: string[] } | null = null;

    const flushList = () => {
        if (!currentList) return;

        if (currentList.type === "ul") {
            elements.push(
                <ul key={`ul-${elements.length}`} className="my-2.5 space-y-1.5 pl-1">
                    {currentList.items.map((item, idx) => (
                        <li key={idx} className="flex items-start gap-2.5 text-sm leading-relaxed text-slate-700 dark:text-slate-300">
                            <span className="mt-2 h-1.5 w-1.5 rounded-full bg-primary/70 shrink-0" />
                            <div className="flex-1 min-w-0">
                                {renderInlineFormatting(item)}
                            </div>
                        </li>
                    ))}
                </ul>
            );
        } else {
            elements.push(
                <ol key={`ol-${elements.length}`} className="my-2.5 space-y-1.5 pl-1">
                    {currentList.items.map((item, idx) => (
                        <li key={idx} className="flex items-start gap-2.5 text-sm leading-relaxed text-slate-700 dark:text-slate-300">
                            <span className="text-xs font-bold text-primary font-mono mt-0.5 shrink-0 w-4 text-right">
                                {idx + 1}.
                            </span>
                            <div className="flex-1 min-w-0">
                                {renderInlineFormatting(item)}
                            </div>
                        </li>
                    ))}
                </ol>
            );
        }

        currentList = null;
    };

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i].trim();

        if (!line) {
            flushList();
            continue;
        }

        // Bullet list item: starts with "* ", "- ", "+ "
        const bulletMatch = line.match(/^[*+-]\s+(.*)$/);
        if (bulletMatch) {
            if (!currentList || currentList.type !== "ul") {
                flushList();
                currentList = { type: "ul", items: [] };
            }
            currentList.items.push(bulletMatch[1]);
            continue;
        }

        // Numbered list item: starts with "1. ", "2. ", etc.
        const numberMatch = line.match(/^\d+\.\s+(.*)$/);
        if (numberMatch) {
            if (!currentList || currentList.type !== "ol") {
                flushList();
                currentList = { type: "ol", items: [] };
            }
            currentList.items.push(numberMatch[1]);
            continue;
        }

        // Non-list item -> flush any pending list
        flushList();

        // Heading: ###
        if (line.startsWith("### ")) {
            elements.push(
                <h4 key={`h3-${i}`} className="font-semibold text-sm text-slate-900 dark:text-white mt-3 mb-1">
                    {renderInlineFormatting(line.slice(4))}
                </h4>
            );
            continue;
        }

        // Heading: ##
        if (line.startsWith("## ")) {
            elements.push(
                <h3 key={`h2-${i}`} className="font-bold text-base text-slate-900 dark:text-white mt-3.5 mb-1.5">
                    {renderInlineFormatting(line.slice(3))}
                </h3>
            );
            continue;
        }

        // Heading: #
        if (line.startsWith("# ")) {
            elements.push(
                <h2 key={`h1-${i}`} className="font-bold text-lg text-slate-900 dark:text-white mt-4 mb-2">
                    {renderInlineFormatting(line.slice(2))}
                </h2>
            );
            continue;
        }

        // Regular paragraph
        elements.push(
            <p key={`p-${i}`} className="text-sm leading-relaxed text-slate-800 dark:text-slate-200 my-1">
                {renderInlineFormatting(line)}
            </p>
        );
    }

    flushList();

    return (
        <div className="space-y-1">
            {elements}
            {isStreaming && (
                <span className="inline-block w-1.5 h-4 ml-0.5 bg-primary animate-pulse rounded-sm align-middle" />
            )}
        </div>
    );
}
