import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Box, Link } from "@mui/material";
import CodeBlock from "./CodeBlock";
import { openExternal } from "../native";

export default function Markdown({ children }: { children: string }) {
  return (
    <Box
      sx={{
        fontSize: 14, lineHeight: 1.6, overflowWrap: "anywhere",
        "& p": { my: 0.75 }, "& h1,& h2,& h3,& h4": { mt: 1.5, mb: 0.75, lineHeight: 1.3 },
        "& h2": { fontSize: 18 }, "& h3": { fontSize: 16 }, "& ul,& ol": { pl: 3, my: 0.5 },
        "& table": { borderCollapse: "collapse", width: "100%", my: 1, fontSize: 13, display: "block", overflowX: "auto" },
        "& th,& td": { border: 1, borderColor: "divider", px: 1, py: 0.5, textAlign: "left", verticalAlign: "top" },
        "& th": { bgcolor: "action.hover" },
        "& blockquote": { borderLeft: 4, borderColor: "warning.main", m: 0, my: 1, px: 1.5, py: 0.5, bgcolor: "action.hover" },
        "& :not(pre) > code": { bgcolor: "action.selected", px: 0.5, borderRadius: 0.5, fontSize: 12.5, fontFamily: "Consolas, monospace" },
      }}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ className, children: code }) {
            const lang = /language-(\w+)/.exec(className || "")?.[1];
            const text = String(code ?? "").replace(/\n$/, "");
            if (!lang && !text.includes("\n")) return <code>{code}</code>;
            return <CodeBlock code={text} language={lang ?? ""} />;
          },
          pre({ children: inner }) {
            return <>{inner}</>;
          },
          a({ href, children: label }) {
            return (
              <Link href={href} onClick={(e) => { e.preventDefault(); if (href) openExternal(href); }}>
                {label}
              </Link>
            );
          },
        }}
      >
        {children}
      </ReactMarkdown>
    </Box>
  );
}
