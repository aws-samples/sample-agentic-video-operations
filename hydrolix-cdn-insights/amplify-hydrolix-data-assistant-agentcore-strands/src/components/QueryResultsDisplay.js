import { useState, useEffect, useMemo } from "react";
import {
  Box,
  Typography,
  IconButton,
  Collapse,
  Tooltip,
  Paper,
  Chip,
  Divider,
} from "@mui/material";
import {
  ContentCopy as CopyIcon,
  KeyboardArrowDown as KeyboardArrowDownIcon,
  KeyboardArrowUp as KeyboardArrowUpIcon,
  SmartToy as AgentIcon,
  ChatBubbleOutline as PromptIcon,
  DataObject as QueryIcon,
} from "@mui/icons-material";
import TableView from "./TableView";

const QueryResultsDisplay = ({ index, answer }) => {
  const [collapsedPapers, setCollapsedPapers] = useState({});
  const [copied, setCopied] = useState(false);

  // Group queries by agent_name
  const agentGroups = useMemo(() => {
    if (!answer?.queryResults?.length) return [];
    const groups = [];
    let currentGroup = null;

    answer.queryResults.forEach((qr) => {
      const agentName = qr.agent_name || "unknown";
      if (!currentGroup || currentGroup.agent_name !== agentName) {
        currentGroup = { agent_name: agentName, queries: [] };
        groups.push(currentGroup);
      }
      currentGroup.queries.push(qr);
    });

    return groups;
  }, [answer]);

  useEffect(() => {
    if (agentGroups.length > 0) {
      const initialState = {};
      agentGroups.forEach((_, g) => {
        initialState[`agent_${index}_${g}`] = g !== 0;
      });
      setCollapsedPapers(initialState);
    }
  }, [index, agentGroups]);

  const togglePaperCollapse = (idx) => {
    setCollapsedPapers((prev) => ({
      ...prev,
      [idx]: !prev[idx],
    }));
  };

  const handleCopyQuery = (query) => {
    navigator.clipboard.writeText(query);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Box>
      {agentGroups.map((group, g) => {
        const groupKey = `agent_${index}_${g}`;
        const isCollapsed = collapsedPapers[groupKey];
        const queryCount = group.queries.length;

        return (
          <Paper
            key={groupKey}
            sx={{
              bgcolor: "rgba(248, 255, 252, 0.05)",
              mb: 2,
              borderRadius: 4,
              overflow: "hidden",
              transition: "all 0.3s ease",
              boxShadow: "rgba(0, 0, 0, 0.05) 0px 4px 12px",
            }}
          >
            {/* Agent Header */}
            <Box
              display="flex"
              alignItems="center"
              justifyContent="space-between"
              p={1}
              onClick={() => togglePaperCollapse(groupKey)}
              sx={{
                borderRadius: isCollapsed ? 4 : "4px 4px 0 0",
                cursor: "pointer",
                backgroundColor: isCollapsed
                  ? "rgba(0,0,0,0.03)"
                  : "transparent",
                border: isCollapsed ? "1px solid" : "none",
                borderBottom: !isCollapsed ? "1px solid" : undefined,
                borderColor: "divider",
              }}
            >
              <Box display="flex" alignItems="center" flexWrap="wrap" gap={1}>
                <Chip
                  icon={<AgentIcon sx={{ fontSize: 16 }} />}
                  label={group.agent_name}
                  size="small"
                  variant="outlined"
                  color="secondary"
                />
                <Typography variant="body2" color="text.secondary">
                  {queryCount} {queryCount === 1 ? "query" : "queries"}
                </Typography>
              </Box>

              <IconButton
                size="small"
                onClick={(e) => {
                  e.stopPropagation();
                  togglePaperCollapse(groupKey);
                }}
              >
                {isCollapsed ? (
                  <KeyboardArrowDownIcon />
                ) : (
                  <KeyboardArrowUpIcon />
                )}
              </IconButton>
            </Box>

            {/* Collapsible Content - all queries for this agent */}
            <Collapse in={!isCollapsed}>
              <Box p={2}>
                {/* Show user prompt once per agent group */}
                {group.queries[0]?.user_prompt && (
                  <Box
                    display="flex"
                    alignItems="flex-start"
                    mb={2}
                    p={1.5}
                    sx={{
                      backgroundColor: "rgba(0, 0, 0, 0.02)",
                      borderRadius: 2,
                      border: "1px solid",
                      borderColor: "divider",
                    }}
                  >
                    <PromptIcon
                      sx={{ fontSize: 18, mr: 1, mt: 0.2, color: "text.secondary" }}
                    />
                    <Box>
                      <Typography variant="caption" color="text.secondary">
                        Prompt
                      </Typography>
                      <Typography variant="body2">
                        {group.queries[0].user_prompt}
                      </Typography>
                    </Box>
                  </Box>
                )}

                {group.queries.map((query_result, q) => {
                  const results = query_result.query_results || [];
                  const hasResults = results.length > 0;

                  return (
                    <Box key={`${groupKey}_q${q}`}>
                      {q > 0 && <Divider sx={{ my: 2 }} />}

                      {/* SQL Query */}
                      <Box
                        mb={1.5}
                        p={1.5}
                        sx={{
                          backgroundColor: "rgba(0, 0, 0, 0.02)",
                          borderRadius: 2,
                          border: "1px solid",
                          borderColor: "divider",
                        }}
                      >
                        <Box display="flex" alignItems="flex-start">
                          <QueryIcon
                            sx={{ fontSize: 18, mr: 1, mt: 0.2, color: "text.secondary" }}
                          />
                          <Box sx={{ flex: 1 }}>
                            <Box display="flex" alignItems="center" gap={0.5}>
                              <Typography variant="caption" color="text.secondary">
                                SQL Query
                              </Typography>
                              <Tooltip title={copied ? "Copied!" : "Copy query"}>
                                <IconButton
                                  size="small"
                                  onClick={() => handleCopyQuery(query_result.query)}
                                  sx={{ p: 0.25 }}
                                >
                                  <CopyIcon sx={{ fontSize: 14 }} />
                                </IconButton>
                              </Tooltip>
                            </Box>
                            <Typography
                              variant="body2"
                              sx={{
                                fontFamily: "monospace",
                                fontSize: "0.82rem",
                                whiteSpace: "pre-wrap",
                                wordBreak: "break-word",
                              }}
                            >
                              {query_result.query}
                            </Typography>
                          </Box>
                        </Box>
                      </Box>

                      {hasResults && <TableView query_results={results} />}
                    </Box>
                  );
                })}
              </Box>
            </Collapse>
          </Paper>
        );
      })}
    </Box>
  );
};

export default QueryResultsDisplay;
