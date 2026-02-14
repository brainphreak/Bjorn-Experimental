/* ========================================
   Network Tab - Host Table
   ======================================== */
'use strict';

const NetworkTab = {
    hosts: [],

    init() {
        const panel = document.getElementById('tab-network');
        panel.innerHTML = '<div id="network-table" class="network-panel"></div>';
    },

    activate() {
        App.startPolling('network', () => this.refresh(), 30000);
    },

    deactivate() {
        App.stopPolling('network');
    },

    async refresh() {
        try {
            const data = await App.api('/netkb_data_json');
            this.hosts = data.hosts || [];
            this.render();
        } catch (e) { /* retry */ }
    },

    render() {
        const container = document.getElementById('network-table');
        if (!this.hosts.length) {
            container.innerHTML = '<div class="empty-state">No hosts discovered yet.</div>';
            return;
        }

        container.innerHTML = this.hosts.map(h => {
            const alive = h.alive === '1';
            const hasCreds = this.hostHasCreds(h);
            const statusCls = hasCreds ? 'pwned' : (alive ? 'alive' : 'dead');
            const ports = (h.ports || '').replace(/;/g, ', ') || 'none';
            const hostname = h.hostname || '';

            // Build attack status badges
            const actions = h.actions || {};
            const badges = this.renderBadges(actions);

            return `
                <div class="host-card ${statusCls}">
                    <div class="host-row-main">
                        <div class="host-status ${statusCls}"></div>
                        <div class="host-info">
                            <span class="host-ip">${h.ip}</span>
                            ${hostname ? '<span class="host-name">' + hostname + '</span>' : ''}
                            <span class="host-mac">${h.mac || ''}</span>
                        </div>
                        <div class="host-ports">${ports}</div>
                    </div>
                    ${badges ? '<div class="host-row-attacks">' + badges + '</div>' : ''}
                </div>
            `;
        }).join('');
    },

    renderBadges(actions) {
        const order = [
            ['SSH', 'SSHBruteforce', 'StealFilesSSH'],
            ['FTP', 'FTPBruteforce', 'StealFilesFTP'],
            ['Telnet', 'TelnetBruteforce', 'StealFilesTelnet'],
            ['SMB', 'SMBBruteforce', 'StealFilesSMB'],
            ['RDP', 'RDPBruteforce', null],
            ['SQL', 'SQLBruteforce', 'StealDataSQL'],
        ];

        const badges = [];
        for (const [proto, bruteKey, stealKey] of order) {
            const bruteVal = actions[bruteKey] || '';
            const stealVal = stealKey ? (actions[stealKey] || '') : '';

            // Skip protocols with no results at all
            if (!bruteVal && !stealVal) continue;

            const bruteOk = bruteVal.toLowerCase().includes('success');
            const bruteFail = bruteVal && !bruteOk;
            const stealOk = stealVal.toLowerCase().includes('success');
            const stealFail = stealVal && !stealOk;

            let cls = 'pending';
            let label = proto;

            if (bruteOk && stealOk) {
                cls = 'full-success';
                label = proto + ' pwned+loot';
            } else if (bruteOk && stealFail) {
                cls = 'partial';
                label = proto + ' pwned';
            } else if (bruteOk && !stealVal) {
                cls = 'success';
                label = proto + ' pwned';
            } else if (bruteFail) {
                cls = 'failed';
                label = proto + ' no creds';
            }

            badges.push('<span class="attack-badge ' + cls + '">' + label + '</span>');
        }

        return badges.join('');
    },

    hostHasCreds(host) {
        const actions = host.actions || {};
        return Object.keys(actions).some(k =>
            k.includes('Bruteforce') && (actions[k] || '').toLowerCase().includes('success')
        );
    }
};

App.registerTab('network', NetworkTab);
