"""Domain Policy Engine for OGK DNS Proxy (FR-F2-03, FR-F2-04, FR-F2-05, FR-F2-06, M1).
Implements O(k) Suffix Trie and O(1) HashSet domain matching, 6-category evaluation,
SafeSearch CNAME enforcement, DoH Canary blocking, and eTLD+1 normalization.
"""
import logging
from typing import Dict, Any, Optional, Tuple, List, Set
import tldextract

logger = logging.getLogger("OGK.DomainEngine")

# Decision Action Constants
ACTION_ALLOW = "ALLOW"
ACTION_BLOCK = "BLOCK"
ACTION_SAFESEARCH = "SAFESEARCH"
ACTION_DOH_CANARY = "DOH_CANARY"

# Canary domain for Firefox DoH disable (RFC/Mozilla spec)
CANARY_DOH_DOMAIN = "use-application-dns.net"

# Popular DoH resolver endpoints to block at DNS level (M3, FR-F2-06)
POPULAR_DOH_ENDPOINTS: Set[str] = {
    "dns.google", "dns.google.com",
    "cloudflare-dns.com", "one.one.one.one",
    "dns.quad9.net", "doh.opendns.com",
    "dns.adguard.com", "doh.cleanbrowsing.org",
    "doh.mullvad.net", "dns.alidns.com"
}

# SafeSearch CNAME mappings (FR-F2-05)
SAFESEARCH_MAP: Dict[str, str] = {
    "google.com": "forcesafesearch.google.com",
    "www.google.com": "forcesafesearch.google.com",
    "google.com.vn": "forcesafesearch.google.com",
    "www.google.com.vn": "forcesafesearch.google.com",
    "bing.com": "strict.bing.com",
    "www.bing.com": "strict.bing.com",
    "duckduckgo.com": "safe.duckduckgo.com",
    "www.duckduckgo.com": "safe.duckduckgo.com",
    "youtube.com": "restrict.youtube.com",
    "www.youtube.com": "restrict.youtube.com",
    "m.youtube.com": "restrict.youtube.com",
    # Google's documented YouTube Restricted Mode hostnames (apps and embeds use these)
    "youtubei.googleapis.com": "restrict.youtube.com",
    "youtube.googleapis.com": "restrict.youtube.com",
    "www.youtube-nocookie.com": "restrict.youtube.com",
}

# Offline tldextract instance
_OFFLINE_EXTRACTOR = tldextract.TLDExtract(suffix_list_urls=None)
_ETLD_CACHE: Dict[str, str] = {}


def _is_ip_literal(value: str) -> bool:
    import ipaddress
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def normalize_etld_plus_one(domain: str) -> str:
    """
    Extracts eTLD+1 from domain string using bundled offline suffix list (F3, BR-07).
    Example: 'sub.school.edu.vn' -> 'school.edu.vn'.
    Falls back to cleaned domain if not applicable (e.g. localhost or IP).
    """
    cleaned = domain.lower().strip().rstrip(".")
    if not cleaned:
        return ""
    if cleaned in _ETLD_CACHE:
        return _ETLD_CACHE[cleaned]

    try:
        ext = _OFFLINE_EXTRACTOR(cleaned)
        # Use top_domain_under_public_suffix (or registered_domain)
        reg_domain = getattr(ext, "top_domain_under_public_suffix", None) or ext.registered_domain
        if reg_domain:
            result = reg_domain
        elif not ext.suffix and ext.domain and not _is_ip_literal(cleaned) and "." in cleaned:
            # TLD not in the public suffix list (e.g. RFC 2606 `.test` / `.example` used by
            # the seed catalog): treat the last label as the suffix -> keep the last two labels
            result = ".".join(cleaned.split(".")[-2:])
        else:
            result = cleaned
    except Exception:
        result = cleaned

    if len(_ETLD_CACHE) < 4096:
        _ETLD_CACHE[cleaned] = result
    return result


class SuffixTrieNode:
    """Node in Suffix Trie with reversed domain labels."""
    def __init__(self):
        self.children: Dict[str, "SuffixTrieNode"] = {}
        self.is_terminal: bool = False
        self.rule: Optional[Dict[str, Any]] = None


class SuffixTrie:
    """
    Suffix Trie storing domain rules indexed by reversed labels.
    Example: 'bad.example.test' is indexed as ['test', 'example', 'bad'].
    Enables O(k) lookup matching exact domain and all subdomains (*.example.test).
    """
    def __init__(self):
        self.root = SuffixTrieNode()

    def insert(self, domain: str, rule: Dict[str, Any]) -> None:
        """Inserts domain rule into trie."""
        clean = domain.lower().strip().rstrip(".")
        if not clean:
            return
        labels = clean.split(".")[::-1]  # reverse labels
        curr = self.root
        for label in labels:
            if label not in curr.children:
                curr.children[label] = SuffixTrieNode()
            curr = curr.children[label]
        curr.is_terminal = True
        curr.rule = rule

    def find_rule(self, domain: str) -> Optional[Dict[str, Any]]:
        """
        Traverses trie to find longest matching suffix rule.
        Matches exact domain and any subdomains.
        """
        clean = domain.lower().strip().rstrip(".")
        if not clean:
            return None
        labels = clean.split(".")[::-1]
        curr = self.root
        matched_rule = None

        for label in labels:
            if label in curr.children:
                curr = curr.children[label]
                if curr.is_terminal:
                    matched_rule = curr.rule
            else:
                break

        return matched_rule


class DomainPolicyEngine:
    """
    High-speed Domain Policy Engine with HashSet O(1) exact matching,
    Suffix Trie O(k) wildcard/subdomain matching, 6 categories,
    Allowlist > Blocklist precedence, and SafeSearch enforcement.
    """

    def __init__(self, safesearch_enabled: bool = True):
        self.safesearch_enabled = safesearch_enabled
        self.trie = SuffixTrie()

        # O(1) HashSets for exact match lookups
        self.exact_allow: Set[str] = set()
        self.exact_block: Set[str] = set()

        # 6 Category default actions
        self.category_actions: Dict[str, str] = {
            "education": "allow",
            "entertainment": "allow",
            "social": "block",
            "gaming": "allow",
            "inappropriate": "block",
            "unclassified": "allow",
        }

    def load_policy(
        self,
        domain_rules: List[Dict[str, Any]],
        category_rules: Optional[Dict[str, str]] = None,
        safesearch_enabled: Optional[bool] = None,
    ) -> None:
        """
        Loads domain rules and category actions into high-speed memory structures.
        Strict precedence: Allowlist > Blocklist.
        """
        self.trie = SuffixTrie()
        self.exact_allow.clear()
        self.exact_block.clear()

        if safesearch_enabled is not None:
            self.safesearch_enabled = safesearch_enabled

        if category_rules:
            self.category_actions.update({k.lower(): v.lower() for k, v in category_rules.items()})

        for r in domain_rules:
            dom = r.get("domain", "").lower().strip().rstrip(".")
            if not dom:
                continue
            cat = r.get("category", "unclassified").lower()
            act = r.get("action", "allow").lower()
            rule_entry = {"domain": dom, "category": cat, "action": act}

            # Insert into Suffix Trie for subdomain matching
            self.trie.insert(dom, rule_entry)

            # Insert into exact match HashSets
            if act == "allow":
                self.exact_allow.add(dom)
            elif act == "block":
                self.exact_block.add(dom)

        logger.info(
            "DomainPolicyEngine loaded %d domain rules (Allow: %d, Block: %d)",
            len(domain_rules), len(self.exact_allow), len(self.exact_block)
        )

    def evaluate(self, qname: str) -> Tuple[str, str, Optional[str]]:
        """
        Evaluates a queried domain name.
        Precedence order:
            1. DoH Canary (use-application-dns.net) -> DOH_CANARY (NXDOMAIN)
            2. DoH Endpoints (dns.google, cloudflare-dns.com...) -> BLOCK (NXDOMAIN)
            3. SafeSearch CNAME mapping (if enabled)
            4. Exact Allowlist (HashSet O(1)) -> ALLOW (Allowlist > Blocklist)
            5. Exact Blocklist (HashSet O(1)) -> BLOCK
            6. Suffix Trie (O(k)) matching:
               - If explicit rule action is 'allow' -> ALLOW
               - If explicit rule action is 'block' -> BLOCK
               - If category is blocked -> BLOCK
               - Otherwise -> ALLOW
            7. Default fallback by category 'unclassified'

        Returns:
            (action, reason, target)
        """
        norm_name = qname.lower().strip().rstrip(".")

        # 1. Check DoH Canary (RFC/Mozilla Firefox) -> Must return NXDOMAIN
        if norm_name == CANARY_DOH_DOMAIN:
            return ACTION_DOH_CANARY, "DoH Canary blocked to disable browser DoH", None

        # 2. Check Popular DoH Endpoints -> Block to force standard DNS
        if norm_name in POPULAR_DOH_ENDPOINTS:
            return ACTION_DOH_CANARY, "DoH endpoint blocked", None

        # 3. Check SafeSearch mappings (if enabled)
        if self.safesearch_enabled and norm_name in SAFESEARCH_MAP:
            target_cname = SAFESEARCH_MAP[norm_name]
            return ACTION_SAFESEARCH, f"Enforcing SafeSearch via {target_cname}", target_cname

        # 4. Strict Precedence: Exact Allowlist (HashSet O(1)) beats everything
        if norm_name in self.exact_allow:
            return ACTION_ALLOW, "Domain explicitly allowed by exact match rule", None

        # 5. Exact Blocklist (HashSet O(1))
        if norm_name in self.exact_block:
            return ACTION_BLOCK, "Domain explicitly blocked by exact match rule", None

        # 6. Suffix Trie matching (O(k)) for domain and subdomains
        matched_rule = self.trie.find_rule(norm_name)
        if matched_rule:
            rule_action = matched_rule.get("action", "allow")
            category = matched_rule.get("category", "unclassified")

            # Explicit allow rule in Trie beats category block
            if rule_action == "allow":
                return ACTION_ALLOW, f"Domain allowed by rule (Category: {category})", None

            if rule_action == "block":
                return ACTION_BLOCK, f"Domain blocked by rule (Category: {category})", None

            # Category-based action
            cat_action = self.category_actions.get(category, "allow")
            if cat_action == "block":
                return ACTION_BLOCK, f"Category '{category}' is blocked", None

            return ACTION_ALLOW, f"Domain allowed (Category: {category})", None

        # 7. Default fallback: check unclassified category
        default_cat_action = self.category_actions.get("unclassified", "allow")
        if default_cat_action == "block":
            return ACTION_BLOCK, "Unclassified domains are blocked", None

        return ACTION_ALLOW, "Allowed by default", None
