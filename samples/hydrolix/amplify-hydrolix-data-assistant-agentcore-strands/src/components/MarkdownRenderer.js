import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";
import { MARKDOWN_SCHEMA } from "../utils/markdownSchema";
import { Box } from "@mui/material";
import "./MarkdownRenderer.css";

const MarkdownRenderer = ({ content }) => {
  return (
    <Box className="markdown-container">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        // Raw HTML in a model answer is parsed, then sanitized: no script, iframe, srcdoc,
        // event handlers, images, or links other than http(s) reach the page (RB11).
        rehypePlugins={[rehypeRaw, [rehypeSanitize, MARKDOWN_SCHEMA]]}
        components={{
          h1: ({ node, children, ...props }) => (
            <h1 className="markdown-heading1" {...props}>
              {children}
            </h1>
          ),
          h2: ({ node, children, ...props }) => (
            <h2 className="markdown-heading2" {...props}>
              {children}
            </h2>
          ),
          h3: ({ node, children, ...props }) => (
            <h3 className="markdown-heading3" {...props}>
              {children}
            </h3>
          ),
          h4: ({ node, children, ...props }) => (
            <h4 className="markdown-heading4" {...props}>
              {children}
            </h4>
          ),
          h5: ({ node, children, ...props }) => (
            <h5 className="markdown-heading5" {...props}>
              {children}
            </h5>
          ),
          h6: ({ node, children, ...props }) => (
            <h6 className="markdown-heading6" {...props}>
              {children}
            </h6>
          ),
          p: ({ node, ...props }) => <p className="markdown-paragraph" {...props} />,
          a: ({ node, children, ...props }) => (
            <a className="markdown-link" {...props} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          ),
          code: ({ node, inline, ...props }) => {
            return inline ? (
              <code className="markdown-inline-code" {...props} />
            ) : (
              <pre className="markdown-code-block">
                <code {...props} />
              </pre>
            );
          },
          ul: ({ node, ...props }) => <ul className="markdown-list markdown-unordered-list" {...props} />,
          ol: ({ node, ...props }) => <ol className="markdown-list markdown-ordered-list" {...props} />,
          li: ({ node, ...props }) => <li className="markdown-list-item" {...props} />,
          blockquote: ({ node, ...props }) => <blockquote className="markdown-blockquote" {...props} />,
          table: ({ node, ...props }) => <table className="markdown-table" {...props} />,
          th: ({ node, ...props }) => <th {...props} />,
          td: ({ node, ...props }) => <td {...props} />,
          br: () => <br />,
          hr: () => <hr className="markdown-hr" />,
          b: ({ node, ...props }) => <strong className="markdown-bold" {...props} />,
          strong: ({ node, ...props }) => <strong className="markdown-bold" {...props} />,
          i: ({ node, ...props }) => <em className="markdown-italic" {...props} />,
          em: ({ node, ...props }) => <em className="markdown-italic" {...props} />,
          u: ({ node, ...props }) => <u {...props} />,
          s: ({ node, ...props }) => <s className="markdown-strike" {...props} />,
          del: ({ node, ...props }) => <del className="markdown-strike" {...props} />,
          sup: ({ node, ...props }) => <sup className="markdown-sup" {...props} />,
          sub: ({ node, ...props }) => <sub className="markdown-sub" {...props} />,
        }}
      >
        {content}
      </ReactMarkdown>
    </Box>
  );
};

export default MarkdownRenderer;